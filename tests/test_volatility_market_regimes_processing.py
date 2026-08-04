from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from processing_signals.processing.volatility_market_regimes.volatility_market_regimes_feature_builder import (
    VolatilityMarketRegimesFeatureBuilder,
)
from processing_signals.processing.volatility_market_regimes.volatility_market_regimes_processor import (
    calculate_trailing_percentile_ranks,
    calculate_trailing_statistics,
    calculate_trailing_z_scores,
    process_volatility_market_regimes,
)


ROOT = Path(__file__).parents[1]


def _input(days: int = 35, hours_per_day: int = 1, mode: str = "bootstrap") -> dict:
    timestamps = [1_700_000_000 + index * 86_400 // hours_per_day for index in range(days * hours_per_day)]
    return {
        "family": "volatility_market_regimes", "stage": "input_preprocessed", "mode": mode,
        "reference_timestamp": timestamps[-1], "execution_timestamp": timestamps[-1] + 1,
        "dimensions": {"asset": "BTC", "symbol": "BTCUSDT", "exchange": "Binance", "interval": "1h"},
        "providers": {
            "coinglass": {"top_position_ratio": {"status": "available", "reason": None, "records": [
                {"timestamp": ts, "long_percent": 55.0, "short_percent": 45.0, "long_short_ratio": 1.2} for ts in timestamps]}},
            "glassnode": {"realized_volatility": {"status": "available", "reason": None, "records": [
                {"timestamp": ts, "value_native": 0.5, "value_percent": 40.0 + index} for index, ts in enumerate(timestamps)]}},
            "deribit": {"volatility_index": {"status": "available", "reason": None, "records": [
                {"timestamp": ts, "open_native": 0.0, "high_native": 0.0, "low_native": 0.0, "close_native": 0.0,
                 "open_percent": 50.0 + index, "high_percent": 51.0 + index, "low_percent": 49.0 + index, "close_percent": 50.0 + index}
                for index, ts in enumerate(timestamps)]}},
        }, "quality": {"status": "ok"},
    }


@pytest.mark.parametrize("field,value", [("family", "other"), ("stage", "raw")])
def test_invalid_identity_returns_invalid_quality(field, value):
    source = _input()
    source[field] = value
    result = process_volatility_market_regimes(source)
    assert result["quality"]["status"] == "invalid"
    assert result["quality"]["errors"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("mode", ["bootstrap", "incremental", "recovery"])
def test_modes_are_preserved(mode):
    assert process_volatility_market_regimes(_input(mode=mode))["mode"] == mode


def test_processing_is_immutable_deterministic_and_strict_json():
    source   = _input()
    original = copy.deepcopy(source)
    first    = process_volatility_market_regimes(source)
    second   = process_volatility_market_regimes(source)
    assert source == original
    assert first == second
    first["features"]["positioning"]["records"][0]["long_percent"] = 0
    assert source == original
    json.dumps(second, ensure_ascii=False, allow_nan=False)


def test_positioning_orders_calculates_current_and_has_no_semantics():
    source = _input(days=3)
    source["providers"]["coinglass"]["top_position_ratio"]["records"].reverse()
    feature = process_volatility_market_regimes(source)["features"]["positioning"]
    assert [row["timestamp"] for row in feature["records"]] == sorted(row["timestamp"] for row in feature["records"])
    assert feature["records"][0]["net_long_percentage_points"] == 10.0
    assert feature["current"] == feature["records"][-1]
    assert not ({"state", "bullish", "bearish", "crowded"} & set(feature["records"][0]))


def test_hourly_union_no_fill_formulas_zero_ratio_and_currents():
    source   = _input(days=3)
    realized = source["providers"]["glassnode"]["realized_volatility"]["records"]
    implied  = source["providers"]["deribit"]["volatility_index"]["records"]
    implied[0]["close_percent"] = 0.0
    realized.pop(1)
    implied.pop(2)
    feature = process_volatility_market_regimes(source)["features"]["volatility_comparison"]
    assert len(feature["records"]) == 3
    assert feature["records"][0]["realized_to_implied_ratio"] is None
    assert feature["records"][1]["realized_volatility_percent"] is None
    assert feature["records"][2]["implied_close_percent"] is None
    assert feature["records"][0]["spread_volatility_points"] == 40.0
    assert feature["records"][0]["implied_premium_volatility_points"] == -40.0
    assert feature["current"]["latest_realized"]["timestamp"] != feature["current"]["latest_implied"]["timestamp"]


@pytest.mark.parametrize("count,status", [(168, "available"), (126, "available"), (125, "partial")])
def test_spread_window_coverage(count, status):
    source  = _input(days=1, hours_per_day=168)
    for provider, dataset in (("coinglass", "top_position_ratio"), ("glassnode", "realized_volatility"), ("deribit", "volatility_index")):
        source["providers"][provider][dataset]["records"] = source["providers"][provider][dataset]["records"][-count:]
    feature = process_volatility_market_regimes(source)["features"]["spread_metrics"]
    assert feature["status"] == status
    assert feature["records_used"] == count
    assert feature["coverage"] == count / 168
    assert feature["value"] == -10.0


def test_no_pairs_makes_spread_unavailable():
    source = _input(days=2)
    source["providers"]["deribit"]["volatility_index"]["records"] = []
    result = process_volatility_market_regimes(source)
    assert result["features"]["spread_metrics"]["status"] == "unavailable"
    assert result["features"]["spread_metrics"]["value"] is None


def test_daily_last_valid_independent_and_real_asof():
    source = _input(days=1, hours_per_day=3)
    result = process_volatility_market_regimes(source)["features"]["daily_regime_basis"]["records"]
    last   = result[-1]
    assert last["realized_volatility_percent"] == 42.0
    assert last["implied_volatility_percent"] == 52.0
    assert last["data_as_of"] in {row["timestamp"] for row in source["providers"]["glassnode"]["realized_volatility"]["records"]}
    assert last["coverage"]["realized_hourly_records"] <= 3


def test_rolling_statistics_ddof_warmup_zero_variance_and_no_future():
    values = [1.0] * 19 + [2.0, 1000.0]
    stats  = calculate_trailing_statistics(values)
    scores = calculate_trailing_z_scores(values, stats)
    assert stats[18] == (None, None)
    assert stats[19][0] == pytest.approx(1.05)
    assert stats[19][1] == pytest.approx(0.22360679774997896)
    assert scores[18] is None
    assert stats[19] == calculate_trailing_statistics(values[:-1])[-1]
    assert calculate_trailing_z_scores([1.0] * 20)[-1] is None


def test_percentile_warmup_midpoint_bounds_and_trailing_window():
    values = [1.0] * 30 + [2.0] * 61
    ranks  = calculate_trailing_percentile_ranks(values)
    assert ranks[28] is None
    assert ranks[29] == 0.5
    assert ranks[-1] == pytest.approx((29 + 0.5 * 61) / 90)
    assert all(0 <= rank <= 1 for rank in ranks if rank is not None)


def test_daily_warmup_current_and_no_downstream_vocabulary():
    short = process_volatility_market_regimes(_input(days=29))
    full  = process_volatility_market_regimes(_input(days=35))
    assert short["features"]["daily_regime_basis"]["current"] is None
    assert short["features"]["daily_regime_basis"]["reason"] == "classification_warmup_incomplete"
    assert full["features"]["daily_regime_basis"]["current"] is not None
    text = json.dumps(full)
    for forbidden in ("regime_label", "confidence", "persistence", "signals", "charts", "widgets", "selectors", "display_window"):
        assert forbidden not in text


@pytest.mark.parametrize("provider,dataset", [("coinglass", "top_position_ratio"), ("glassnode", "realized_volatility"), ("deribit", "volatility_index")])
def test_provider_unavailable_degrades_without_fabricating(provider, dataset):
    source = _input(days=35)
    source["providers"][provider][dataset].update(status="unavailable", reason="provider_unavailable", records=[])
    result = process_volatility_market_regimes(source)
    assert result["quality"]["status"] == "partial"
    assert result["quality"]["recovery_required"] is True
    if provider in {"glassnode", "deribit"}:
        assert result["features"]["spread_metrics"]["value"] is None


def test_invalid_numbers_duplicates_and_bool_are_explicit():
    for value in (True, float("nan"), float("inf")):
        source = _input()
        source["providers"]["glassnode"]["realized_volatility"]["records"][0]["value_percent"] = value
        assert process_volatility_market_regimes(source)["quality"]["status"] == "invalid"
    source = _input()
    source["providers"]["glassnode"]["realized_volatility"]["records"].append(copy.deepcopy(source["providers"]["glassnode"]["realized_volatility"]["records"][0]))
    assert process_volatility_market_regimes(source)["quality"]["status"] == "invalid"


def test_modes_with_same_history_have_identical_features():
    outputs = [process_volatility_market_regimes(_input(mode=mode))["features"] for mode in ("bootstrap", "incremental", "recovery")]
    assert outputs[0] == outputs[1] == outputs[2]


def test_feature_builder_copies_and_contains_no_math():
    packages = [{"status": "available", "records": [{"value": 1}]} for _ in range(4)]
    before   = copy.deepcopy(packages)
    result   = VolatilityMarketRegimesFeatureBuilder().build(*packages)
    result["positioning"]["records"][0]["value"] = 2
    assert packages == before
    path = ROOT / "src/processing_signals/processing/volatility_market_regimes/volatility_market_regimes_feature_builder.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.BinOp) for node in ast.walk(tree))


def test_frozen_input_hashes_are_unchanged():
    expected = {
        "src/processing_signals/input/volatility_market_regimes/volatility_market_regimes_data_raw_extract.py": "ba816680d9c1f39d69eb587395402a0658b53c9b97b5b2585fa8b92a05624f6c",
        "src/processing_signals/input/volatility_market_regimes/volatility_market_regimes_data_raw_preprocessing.py": "fb5072f855134d88e57ecfa8796a8fcaad742c2f8da7e32980087dfe118bcac5",
        "tests/test_volatility_market_regimes_input_vertical.py": "c6ec23e344256279dfbb1826e56f0d749c83def91113140c030cdca6717d0336",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
