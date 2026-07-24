from __future__ import annotations

from typing import Any

from processing_signals.input.prices_ohlcv.prices_ohlcv_data_raw_extract import (
    BOOTSTRAP_TIMEFRAMES,
    PricesOhlcvRawExtractor,
    build_prices_fetch_plan,
)
from processing_signals.input.prices_ohlcv.prices_ohlcv_data_raw_preprocessing import (
    PricesOhlcvInputPreprocessor,
    build_general_price_records,
    run_prices_ohlcv_input,
)


def _fetcher_factory(calls: list[dict[str, Any]]):
    def fetcher(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        params           = kwargs["params"]
        market_offset    = 20.0 if kwargs["endpoint_id"] == "futures_ohlcv" else 0.0
        timeframe_offset = float(BOOTSTRAP_TIMEFRAMES.index(params["interval"]))
        base             = 100.0 + market_offset + timeframe_offset
        return {
            "code": "0",
            "msg": "success",
            "data": [
                {
                    "time": 1_784_700_000_000,
                    "open": base,
                    "high": base + 4.0,
                    "low": base - 2.0,
                    "close": base + 2.0,
                    "volume": 1_000.0 + market_offset,
                }
            ],
        }

    return fetcher


def test_bootstrap_fetches_two_markets_and_builds_six_general_timeframes() -> None:
    calls: list[dict[str, Any]] = []

    output = run_prices_ohlcv_input(
        fetcher=_fetcher_factory(calls),
        requested_mode="bootstrap",
    )

    assert len(calls) == 12
    assert {call["endpoint_id"] for call in calls} == {"spot_ohlcv", "futures_ohlcv"}
    assert {call["params"]["interval"] for call in calls} == set(BOOTSTRAP_TIMEFRAMES)
    assert all(call["params"]["limit"] == 500 for call in calls)
    assert output["mode"] == "bootstrap"
    assert set(output["markets"]) == {"spot", "futures", "general"}
    assert set(output["markets"]["general"]["timeframes"]) == set(BOOTSTRAP_TIMEFRAMES)

    general = output["markets"]["general"]["timeframes"]["1m"]["records"][0]
    assert general == {
        "timestamp": 1_784_700_000,
        "open": 110.0,
        "high": 114.0,
        "low": 108.0,
        "close": 112.0,
        "spot_volume_usd": 1_000.0,
        "futures_volume_usd": 1_020.0,
        "combined_volume_usd": 2_020.0,
        "construction": "spot_futures_arithmetic_mean",
    }
    assert output["quality"]["recovery_required"] is False


def test_incremental_plan_only_fetches_1m_and_15m_with_bounded_limits() -> None:
    plan = build_prices_fetch_plan(
        mode="incremental",
        incremental_limits={"1m": 3, "15m": 4},
    )

    assert len(plan) == 4
    assert {(item["market"], item["timeframe"]) for item in plan} == {
        ("spot", "1m"),
        ("spot", "15m"),
        ("futures", "1m"),
        ("futures", "15m"),
    }
    assert {item["timeframe"]: item["limit"] for item in plan} == {"1m": 3, "15m": 4}


def test_general_never_fabricates_a_candle_when_one_market_is_missing() -> None:
    spot = [
        {"timestamp": 100, "open": 10, "high": 12, "low": 9, "close": 11, "volume_usd": 5},
        {"timestamp": 200, "open": 11, "high": 13, "low": 10, "close": 12, "volume_usd": 6},
    ]
    futures = [
        {"timestamp": 100, "open": 12, "high": 14, "low": 11, "close": 13, "volume_usd": 8},
    ]

    general = build_general_price_records(spot, futures)

    assert [record["timestamp"] for record in general["records"]] == [100]
    assert general["unavailable_records"] == [
        {
            "timestamp": 200,
            "general_status": "unavailable",
            "reason": "missing_futures_candle",
        }
    ]


def test_recovery_plan_fetches_only_requested_gap() -> None:
    plan = build_prices_fetch_plan(
        mode="recovery",
        recovery_requests=[
            {
                "market": "futures",
                "timeframe": "15m",
                "limit": 40,
                "start_time": 100,
                "end_time": 200,
            }
        ],
    )

    assert plan == [
        {
            "market": "futures",
            "timeframe": "15m",
            "limit": 40,
            "start_time": 100,
            "end_time": 200,
        }
    ]


def test_oo_objects_are_directly_composable() -> None:
    calls: list[dict[str, Any]] = []
    extractor = PricesOhlcvRawExtractor(
        fetcher=_fetcher_factory(calls),
        symbol="btcusdt",
        exchange="Binance",
    )
    preprocessor = PricesOhlcvInputPreprocessor(raw_extractor=extractor)

    output = preprocessor.run(requested_mode="bootstrap")

    assert output["family"] == "prices_ohlcv"
    assert output["markets"]["spot"]["symbol"] == "btcusdt"
    assert all(call["params"]["symbol"] == "BTCUSDT" for call in calls)
    assert len(calls) == 12
