from __future__ import annotations

from copy import deepcopy
import json

import pytest

from processing_signals.processing.prices_ohlcv.prices_ohlcv_feature_builder import (
    build_prices_features,
)
from processing_signals.processing.prices_ohlcv.prices_ohlcv_processor import (
    TIMEFRAME_SECONDS,
    aggregate_ohlcv_bucket,
    build_general_ohlcv_record,
    calculate_spot_futures_comparison,
    find_affected_buckets,
    rebuild_general_timeframe,
    run_prices_ohlcv_processing,
    update_market_timeframes,
)
from processing_signals.processing.processing_pipeline import PROCESSING_FAMILY_HANDLERS


TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")


def _records(count: int, step: int, *, start: int = 0, offset: float = 0.0) -> list[dict]:
    rows = []
    for index in range(count):
        base = 100.0 + offset + index
        rows.append(
            {
                "timestamp": start + index * step,
                "open": base,
                "high": base + 3.0,
                "low": base - 2.0,
                "close": base + 1.0,
                "volume_usd": 10.0 + index,
            }
        )
    return rows


def _aggregate(records: list[dict], source: str, target: str, *, now: int = 999_999) -> dict:
    return aggregate_ohlcv_bucket(
        records,
        source_timeframe=source,
        target_timeframe=target,
        now_timestamp=now,
    )


@pytest.mark.parametrize(
    ("count", "source", "target", "step"),
    [
        (5, "1m", "5m", 60),
        (4, "15m", "1h", 900),
        (16, "15m", "4h", 900),
        (96, "15m", "1d", 900),
    ],
)
def test_expected_source_records_produce_one_closed_bucket(
    count: int, source: str, target: str, step: int
) -> None:
    result = _aggregate(_records(count, step), source, target)
    assert result["source_records"] == count
    assert result["expected_source_records"] == count
    assert result["is_closed"] is True
    assert result["is_partial"] is False


def test_fifteen_one_minute_records_produce_three_five_minute_buckets() -> None:
    records  = _records(15, 60)
    affected = find_affected_buckets(records, target_timeframe="5m")
    assert affected == [0, 300, 600]


def test_fifteen_one_minute_records_are_aggregated_into_three_records() -> None:
    source = _records(15, 60)
    market = {
        "timeframes": {
            "1m": {"records": source, "incoming_records": source},
        }
    }
    updated = update_market_timeframes(market, mode="incremental", now_timestamp=10_000)
    derived = updated["timeframes"]["5m"]["records"]
    assert [row["timestamp"] for row in derived] == [0, 300, 600]
    assert all(row["source_records"] == 5 for row in derived)


def test_ohlcv_aggregation_rules() -> None:
    records = _records(5, 60)
    records[2]["high"] = 999.0
    records[3]["low"] = 1.0
    result = _aggregate(records, "1m", "5m")
    assert result["open"] == records[0]["open"]
    assert result["close"] == records[-1]["close"]
    assert result["high"] == 999.0
    assert result["low"] == 1.0
    assert result["volume_usd"] == sum(row["volume_usd"] for row in records)


def test_incomplete_bucket_is_partial() -> None:
    result = _aggregate(_records(4, 60), "1m", "5m")
    assert result["is_closed"] is False
    assert result["is_partial"] is True


def test_complete_current_bucket_is_not_closed_before_bucket_end() -> None:
    records = _records(5, 60, start=1_000 - (1_000 % 300))
    result  = aggregate_ohlcv_bucket(
        records,
        source_timeframe="1m",
        target_timeframe="5m",
        now_timestamp=records[0]["timestamp"] + 299,
    )
    assert result["source_records"] == 5
    assert result["is_closed"] is False
    assert result["is_partial"] is True


def test_one_incoming_1m_recomputes_only_its_5m_bucket() -> None:
    source = _records(10, 60)
    market = {
        "timeframes": {
            "1m": {"records": source, "incoming_records": [source[6]]},
            "5m": {"records": [_aggregate(source[:5], "1m", "5m")], "incoming_records": []},
        }
    }
    updated = update_market_timeframes(market, mode="incremental", now_timestamp=10_000)
    assert [row["timestamp"] for row in updated["timeframes"]["5m"]["incoming_records"]] == [300]
    assert [row["timestamp"] for row in updated["timeframes"]["5m"]["records"]] == [0, 300]


def test_one_incoming_15m_recomputes_1h_4h_and_1d_buckets() -> None:
    source = _records(96, 900)
    market = {
        "timeframes": {
            "15m": {"records": source, "incoming_records": [source[20]]},
        }
    }
    updated    = update_market_timeframes(market, mode="incremental", now_timestamp=200_000)
    timeframes = updated["timeframes"]
    assert len(timeframes["1h"]["incoming_records"]) == 1
    assert len(timeframes["4h"]["incoming_records"]) == 1
    assert len(timeframes["1d"]["incoming_records"]) == 1
    assert timeframes["1h"]["incoming_records"][0]["timestamp"] == 18_000
    assert timeframes["4h"]["incoming_records"][0]["timestamp"] == 14_400
    assert timeframes["1d"]["incoming_records"][0]["timestamp"] == 0


def test_general_uses_synchronized_arithmetic_mean_and_separate_volume() -> None:
    spot    = _records(1, 60, offset=0)[0]
    futures = _records(1, 60, offset=20)[0]
    result  = build_general_ohlcv_record(spot_record=spot, futures_record=futures)
    assert result["open"] == 110.0
    assert result["close"] == 111.0
    assert "volume_usd" not in result
    assert result["spot_volume_usd"] == 10.0
    assert result["futures_volume_usd"] == 10.0
    assert result["combined_volume_usd"] == 20.0
    assert result["is_synthetic"] is True


@pytest.mark.parametrize(
    ("spot", "futures", "reason"),
    [
        ([], _records(1, 60), "missing_spot_candle"),
        (_records(1, 60), [], "missing_futures_candle"),
    ],
)
def test_general_never_invents_a_missing_market(
    spot: list[dict], futures: list[dict], reason: str
) -> None:
    result = rebuild_general_timeframe(spot, futures)
    assert result["records"] == []
    assert result["unavailable_records"][0]["reason"] == reason


def test_basis_and_deviation_are_numeric_and_correct() -> None:
    spot    = _records(1, 60, offset=0)[0]
    futures = _records(1, 60, offset=20)[0]
    general = build_general_ohlcv_record(spot_record=spot, futures_record=futures)
    markets = {
        name: {"timeframes": {tf: {"records": []} for tf in TIMEFRAMES}}
        for name in ("spot", "futures", "general")
    }
    markets["spot"]["timeframes"]["1m"]["records"] = [spot]
    markets["futures"]["timeframes"]["1m"]["records"] = [futures]
    markets["general"]["timeframes"]["1m"]["records"] = [general]
    current = calculate_spot_futures_comparison(markets)["by_timeframe"]["1m"]["current"]
    assert current["basis_usd"] == 20.0
    assert current["basis_percent"] == pytest.approx((121 / 101 - 1) * 100)
    assert current["spot_general_deviation_percent"] == pytest.approx((101 / 111 - 1) * 100)
    assert current["futures_general_deviation_percent"] == pytest.approx((121 / 111 - 1) * 100)


def test_zero_spot_close_is_reported_and_not_divided() -> None:
    spot    = _records(1, 60)[0]
    futures = _records(1, 60, offset=20)[0]
    spot["close"] = 0.0
    general = build_general_ohlcv_record(spot_record=spot, futures_record=futures)
    markets = {
        name: {"timeframes": {tf: {"records": []} for tf in TIMEFRAMES}}
        for name in ("spot", "futures", "general")
    }
    markets["spot"]["timeframes"]["1m"]["records"] = [spot]
    markets["futures"]["timeframes"]["1m"]["records"] = [futures]
    markets["general"]["timeframes"]["1m"]["records"] = [general]
    comparison = calculate_spot_futures_comparison(markets)
    assert comparison["by_timeframe"]["1m"]["series"] == []
    assert comparison["warnings"] == ["1m/0: zero denominator"]


def _bootstrap_input() -> dict:
    markets = {}
    for market, offset in (("spot", 0.0), ("futures", 20.0)):
        markets[market] = {
            "timeframes": {
                timeframe: {
                    "records": _records(2, TIMEFRAME_SECONDS[timeframe], offset=offset),
                    "incoming_records": _records(2, TIMEFRAME_SECONDS[timeframe], offset=offset),
                }
                for timeframe in TIMEFRAMES
            }
        }
    markets["general"] = {"timeframes": {}}
    return {"family": "prices_ohlcv", "stage": "input", "mode": "bootstrap", "markets": markets}


def test_bootstrap_preserves_six_direct_timeframes_and_rebuilds_general() -> None:
    output = run_prices_ohlcv_processing(_bootstrap_input(), now_timestamp=999_999)
    for market in ("spot", "futures", "general"):
        assert tuple(output["markets"][market]["timeframes"]) == TIMEFRAMES
        assert all(output["markets"][market]["timeframes"][tf]["records"] for tf in TIMEFRAMES)


def test_bootstrap_does_not_replace_direct_history_with_short_source_window() -> None:
    input_contract = _bootstrap_input()
    direct_5m      = _records(500, 300)
    input_contract["markets"]["spot"]["timeframes"]["5m"]["records"] = direct_5m
    output = run_prices_ohlcv_processing(input_contract, now_timestamp=999_999)
    assert output["markets"]["spot"]["timeframes"]["5m"]["records"] == direct_5m


def test_incremental_uses_input_general_as_history_when_processing_state_is_absent() -> None:
    input_contract = _bootstrap_input()
    input_contract["mode"] = "incremental"
    historical = [
        build_general_ohlcv_record(spot_record=spot, futures_record=futures)
        for spot, futures in zip(
            input_contract["markets"]["spot"]["timeframes"]["1m"]["records"],
            input_contract["markets"]["futures"]["timeframes"]["1m"]["records"],
            strict=True,
        )
    ]
    input_contract["markets"]["general"]["timeframes"] = {
        timeframe: {"records": deepcopy(historical), "incoming_records": []}
        for timeframe in TIMEFRAMES
    }
    for timeframe in TIMEFRAMES:
        input_contract["markets"]["spot"]["timeframes"][timeframe]["incoming_records"] = []
        input_contract["markets"]["futures"]["timeframes"][timeframe]["incoming_records"] = []

    output = run_prices_ohlcv_processing(input_contract, now_timestamp=999_999)
    assert output["markets"]["general"]["timeframes"]["1m"]["records"] == historical


def test_market_selector_defaults_to_general() -> None:
    output   = run_prices_ohlcv_processing(_bootstrap_input(), now_timestamp=999_999)
    selector = output["features"]["market_selector"]
    assert selector == {
        "default_market": "general",
        "available_markets": ["general", "spot", "futures"],
        "timeframes": list(TIMEFRAMES),
    }


def test_feature_builder_only_organizes_numbers_and_indicator_placeholders() -> None:
    markets    = run_prices_ohlcv_processing(_bootstrap_input(), now_timestamp=999_999)["markets"]
    comparison = calculate_spot_futures_comparison(markets)
    features   = build_prices_features(markets=markets, comparison=comparison)
    assert features["indicators"] == {"general": {}, "spot": {}, "futures": {}}
    serialized = json.dumps(features).lower()
    for semantic_label in ("bullish", "bearish", "neutral", "premium", "discount"):
        assert semantic_label not in serialized


def test_processing_does_not_mutate_input_contract() -> None:
    input_contract = _bootstrap_input()
    snapshot       = deepcopy(input_contract)
    run_prices_ohlcv_processing(input_contract, now_timestamp=999_999)
    assert input_contract == snapshot


def test_processing_pipeline_preserves_prices_while_registering_long_short_liquidations() -> None:
    assert tuple(PROCESSING_FAMILY_HANDLERS) == ("prices_ohlcv", "long_short_liquidations", "on_chain_miners", "etf_exchange_flows")
    assert PROCESSING_FAMILY_HANDLERS["prices_ohlcv"] is run_prices_ohlcv_processing
