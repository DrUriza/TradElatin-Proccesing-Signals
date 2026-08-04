from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from processing_signals.classification.volatility_market_regimes.volatility_market_regimes_classifier import (
    DAY_SECONDS,
    build_regime_transition_events,
    calculate_regime_confidence,
    calculate_regime_distribution,
    calculate_regime_persistence,
    calculate_regime_statistics,
    classify_daily_regime_record,
    classify_percentile_regime,
    classify_positioning_record,
    classify_regime_agreement,
    classify_spread_context,
    classify_volatility_market_regimes,
    validate_volatility_market_regimes_processing_contract,
)
from processing_signals.processing.volatility_market_regimes.volatility_market_regimes_processor import process_volatility_market_regimes


ROOT = Path(__file__).parents[1]


def _input(days: int = 40, mode: str = "bootstrap") -> dict:
    timestamps = [1_699_920_000 + index * DAY_SECONDS for index in range(days)]
    return {
        "family": "volatility_market_regimes", "stage": "input_preprocessed", "mode": mode,
        "reference_timestamp": timestamps[-1], "execution_timestamp": timestamps[-1] + 60,
        "dimensions": {"asset": "BTC", "symbol": "BTCUSDT", "exchange": "Binance", "interval": "1h"},
        "providers": {
            "coinglass": {"top_position_ratio": {"status": "available", "reason": None, "records": [
                {"timestamp": ts, "long_percent": 52.0, "short_percent": 48.0, "long_short_ratio": 1.08} for ts in timestamps]}},
            "glassnode": {"realized_volatility": {"status": "available", "reason": None, "records": [
                {"timestamp": ts, "value_native": 0.3, "value_percent": 30.0 + index} for index, ts in enumerate(timestamps)]}},
            "deribit": {"volatility_index": {"status": "available", "reason": None, "records": [
                {"timestamp": ts, "open_native": 0.0, "high_native": 0.0, "low_native": 0.0, "close_native": 0.0,
                 "open_percent": 35.0 + index, "high_percent": 36.0 + index, "low_percent": 34.0 + index, "close_percent": 35.0 + index}
                for index, ts in enumerate(timestamps)]}},
        }, "quality": {"status": "ok"},
    }


def _processing(mode: str = "bootstrap") -> dict:
    return process_volatility_market_regimes(_input(mode=mode))


def _daily(rank: object = 0.5, implied: object = 0.5, timestamp: int = 1_700_000_000, ratio: float | None = 1.0, status: str = "available") -> dict:
    return {
        "timestamp": timestamp, "data_as_of": timestamp + 1, "status": status,
        "realized_volatility_percent": 45.0, "implied_volatility_percent": 50.0, "spread_volatility_points": -5.0,
        "realized_z_score_30d": 0.1, "implied_z_score_30d": 0.2, "spread_z_score_30d": -0.1,
        "realized_percentile_rank_90d": rank, "implied_percentile_rank_90d": implied, "spread_percentile_rank_90d": 0.4,
        "long_short_ratio": ratio, "net_long_percentage_points": 2.0,
    }


@pytest.mark.parametrize("field,value", [("family", "other"), ("stage", "input_preprocessed")])
def test_validation_rejects_wrong_identity(field, value):
    processing = _processing()
    processing[field] = value
    with pytest.raises(ValueError):
        validate_volatility_market_regimes_processing_contract(processing)
    assert classify_volatility_market_regimes(processing)["quality"]["status"] == "invalid"


@pytest.mark.parametrize("mode", ["bootstrap", "incremental", "recovery"])
def test_mode_is_preserved(mode):
    assert classify_volatility_market_regimes(_processing(mode))["mode"] == mode


@pytest.mark.parametrize("rank,state", [(0.0, "low_vol"), (1 / 3, "normal"), (0.5, "normal"), (2 / 3, "normal"), (1.0, "high_vol")])
def test_percentile_boundaries(rank, state):
    assert classify_percentile_regime(rank) == state


@pytest.mark.parametrize("rank", [-0.01, 1.01, float("nan"), float("inf"), True])
def test_invalid_percentiles_are_rejected(rank):
    with pytest.raises(ValueError):
        classify_percentile_regime(rank)
    assert classify_daily_regime_record(_daily(rank=rank))["status"] == "invalid"


@pytest.mark.parametrize("realized,implied,agreement", [
    ("normal", "normal", "confirmed"), ("low_vol", "normal", "implied_higher"), ("high_vol", "normal", "implied_lower"),
    ("normal", "high_vol", "implied_leads_higher"), ("normal", "low_vol", "implied_leads_lower"),
    ("low_vol", "high_vol", "divergent"), ("high_vol", "low_vol", "divergent"), ("normal", None, "unavailable"),
])
def test_agreement_matrix(realized, implied, agreement):
    assert classify_regime_agreement(realized, implied) == agreement


def test_realized_is_primary_and_implied_does_not_replace_it():
    divergent = classify_daily_regime_record(_daily(rank=0.1, implied=0.9))
    absent    = classify_daily_regime_record(_daily(rank=None, implied=0.9))
    assert divergent["regime"] == "low_vol"
    assert absent["regime"] is None
    assert absent["reason"] == "realized_percentile_unavailable"


@pytest.mark.parametrize("agreement,factor", [("confirmed", 1.0), ("divergent", 0.5), ("unavailable", 0.65)])
def test_confidence_factors_bounds_and_meaning(agreement, factor):
    result = calculate_regime_confidence(0.5, "normal", agreement)
    assert result["agreement_factor"] == factor
    assert 0 <= result["confidence_score"] <= 1
    assert "probability" not in result


@pytest.mark.parametrize("rank,state", [(0.5, "high"), (0.42, "medium"), (1 / 3, "low")])
def test_confidence_states(rank, state):
    regime = classify_percentile_regime(rank)
    assert calculate_regime_confidence(rank, regime, "confirmed")["confidence_state"] == state


def test_daily_record_preserves_processing_basis_without_recalculation():
    source = _daily(rank=0.25, implied=0.75)
    result = classify_daily_regime_record(source)
    for field in (
        "spread_volatility_points", "realized_z_score_30d", "implied_z_score_30d",
        "realized_percentile_rank_90d", "implied_percentile_rank_90d", "spread_percentile_rank_90d",
    ):
        assert result["basis"][field] == source[field]


def test_positioning_absence_degrades_but_does_not_remove_regime():
    result = classify_daily_regime_record(_daily(ratio=None))
    assert result["regime"] == "normal"
    assert result["status"] == "partial"
    assert result["reason"] == "positioning_context_unavailable"


def _classified(timestamp: int, regime: str | None, status: str = "available") -> dict:
    return {"timestamp": timestamp, "regime": regime, "status": status, "confidence_score": 0.5, "data_as_of": timestamp, "persistence_days": None}


def test_persistence_consecutive_changes_gaps_and_invalid_records():
    start   = 1_700_000_000
    records = [
        _classified(start, "normal"), _classified(start + DAY_SECONDS, "normal"),
        _classified(start + 2 * DAY_SECONDS, "high_vol"), _classified(start + 4 * DAY_SECONDS, "high_vol"),
        _classified(start + 5 * DAY_SECONDS, None, "unavailable"), _classified(start + 6 * DAY_SECONDS, "high_vol"),
        _classified(start + 7 * DAY_SECONDS, None, "invalid"), _classified(start + 8 * DAY_SECONDS, "high_vol"),
    ]
    calculate_regime_persistence(records)
    assert [record["persistence_days"] for record in records] == [1, 2, 1, 1, None, 1, None, 1]


def test_current_ignores_unavailable_tail():
    processing = _processing()
    daily      = processing["features"]["daily_regime_basis"]["records"]
    daily[-1]["realized_percentile_rank_90d"] = None
    result = classify_volatility_market_regimes(processing)["classifications"]["daily_regimes"]
    assert result["current"]["timestamp"] < daily[-1]["timestamp"]


def test_distribution_counts_shares_empty_and_uses_latest_data_timestamp():
    start   = 1_700_000_000
    records = [_classified(start + index * DAY_SECONDS, state) for index, state in enumerate(("low_vol", "normal", "normal", "high_vol"))]
    calculate_regime_persistence(records)
    result = calculate_regime_distribution(records)
    assert result["full_history"]["counts"] == {"low_vol": 1, "normal": 2, "high_vol": 1}
    assert sum(result["full_history"]["shares"].values()) == pytest.approx(1.0)
    assert result["trailing_30d"]["window_end_timestamp"] == records[-1]["timestamp"]
    assert calculate_regime_distribution([])["full_history"]["status"] == "unavailable"


def test_distribution_trailing_30_days_does_not_use_future_reference():
    start   = 1_700_000_000
    records = [_classified(start + index * DAY_SECONDS, "normal") for index in range(40)]
    result  = calculate_regime_distribution(records)["trailing_30d"]
    assert result["classified_days"] == 30
    assert result["window_start_timestamp"] == records[-30]["timestamp"]


def test_episode_statistics_and_current_episode():
    start   = 1_700_000_000
    states  = ("normal", "normal", "high_vol", "normal", "normal", "normal")
    records = [_classified(start + index * DAY_SECONDS, state) for index, state in enumerate(states)]
    calculate_regime_persistence(records)
    stats = {row["regime"]: row for row in calculate_regime_statistics(records, records[-1])}
    assert stats["normal"]["episode_count"] == 2
    assert stats["normal"]["average_episode_days"] == 2.5
    assert stats["normal"]["maximum_episode_days"] == 3
    assert stats["normal"]["current_episode_days"] == 3
    assert stats["high_vol"]["current_episode_days"] == 0


def test_transitions_are_consecutive_unique_deterministic_and_referenced_once():
    start   = 1_700_000_000
    records = [_classified(start, "low_vol"), _classified(start + DAY_SECONDS, "normal"),
               _classified(start + 2 * DAY_SECONDS, "normal"), _classified(start + 4 * DAY_SECONDS, "high_vol"),
               _classified(start + 5 * DAY_SECONDS, "normal")]
    first = build_regime_transition_events(records)
    assert first == build_regime_transition_events(records)
    assert len(first["by_id"]) == len(first["regime_transition_ids"]) == 2
    assert set(first["regime_transition_ids"]) == set(first["by_id"])
    assert list(first["by_id"].values())[0]["transition_direction"] == "volatility_expansion"
    assert list(first["by_id"].values())[1]["transition_direction"] == "volatility_contraction"


@pytest.mark.parametrize("ratio,state,crowding", [
    (0.66, "short_bias", "extreme_short"), (0.95, "balanced", "normal"), (1.05, "balanced", "normal"), (1.06, "long_bias", "normal"), (1.5, "long_bias", "extreme_long"),
])
def test_positioning_thresholds(ratio, state, crowding):
    record = {"timestamp": 1, "long_percent": 50.0, "short_percent": 50.0, "long_short_ratio": ratio, "net_long_percentage_points": 0.0}
    result = classify_positioning_record(record)
    assert result["positioning_state"] == state
    assert result["crowding_state"] == crowding
    assert not ({"bullish", "bearish", "buy", "sell"} & set(result.values()))


@pytest.mark.parametrize("value,state", [(-1.0, "realized_below_implied"), (0.0, "balanced"), (1.0, "realized_above_implied"), (None, "unavailable")])
def test_spread_context_interprets_without_recalculating(value, state):
    source = {"status": "available" if value is not None else "unavailable", "reason": None if value is not None else "no_pairs", "value": value,
              "unit": "volatility_points", "basis": "realized_minus_implied", "window": "7d", "records_used": 10, "coverage": 0.1,
              "window_start_timestamp": 1, "window_end_timestamp": 2}
    result = classify_spread_context(source)
    assert result["value"] == value
    assert result["spread_state"] == state


def test_partial_spread_stays_partial_and_processing_partial_degrades_quality():
    processing = _processing()
    result     = classify_volatility_market_regimes(processing)
    assert processing["features"]["spread_metrics"]["status"] == "partial"
    assert result["classifications"]["spread_context"]["status"] == "partial"
    assert result["quality"]["status"] == "partial"


def test_all_available_contract_can_produce_quality_ok():
    processing = _processing()
    processing["quality"]["status"] = "ok"
    for feature in processing["features"].values():
        feature["status"], feature["reason"] = "available", None
    for record in processing["features"]["daily_regime_basis"]["records"]:
        record["realized_percentile_rank_90d"] = 0.5
        record["implied_percentile_rank_90d"]  = 0.5
    result = classify_volatility_market_regimes(processing)
    assert result["quality"]["status"] == "ok"


def test_processing_invalid_produces_controlled_invalid_json():
    processing = _processing()
    processing["quality"]["status"] = "invalid"
    result = classify_volatility_market_regimes(processing)
    assert result["quality"]["status"] == "invalid"
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=False)


def test_immutable_deterministic_strict_and_no_presentation_vocabulary():
    processing = _processing()
    original   = copy.deepcopy(processing)
    first      = classify_volatility_market_regimes(processing)
    second     = classify_volatility_market_regimes(processing)
    assert processing == original
    assert first == second
    first["classifications"]["daily_regimes"]["records"][0]["basis"]["realized_volatility_percent"] = 0
    assert processing == original
    text = json.dumps(second, ensure_ascii=False, allow_nan=False, sort_keys=False)
    for forbidden in ("charts", "widgets", "selectors", "badges", "display_window", "probability", "bullish", "bearish", '"buy"', '"sell"'):
        assert forbidden not in text


def test_modes_with_same_features_have_same_semantics():
    outputs = []
    for mode in ("bootstrap", "incremental", "recovery"):
        result = classify_volatility_market_regimes(_processing(mode))
        result.pop("mode")
        outputs.append(result)
    assert outputs[0] == outputs[1] == outputs[2]


def test_classifier_does_not_recalculate_processing_or_import_input():
    path    = ROOT / "src/processing_signals/classification/volatility_market_regimes/volatility_market_regimes_classifier.py"
    source  = path.read_text(encoding="utf-8")
    tree    = ast.parse(source)
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not any("input" in ast.unparse(node) or "processing.math" in ast.unparse(node) for node in imports)
    function_names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for forbidden in ("calculate_rolling_mean", "calculate_rolling_std", "calculate_z_score", "calculate_percentile_rank", "resample", "interpolate"):
        assert forbidden not in function_names
    assert "providers" not in source


def test_frozen_input_processing_and_classifier_hashes_are_unchanged():
    expected = {
        "src/processing_signals/input/volatility_market_regimes/volatility_market_regimes_data_raw_extract.py": "ba816680d9c1f39d69eb587395402a0658b53c9b97b5b2585fa8b92a05624f6c",
        "src/processing_signals/input/volatility_market_regimes/volatility_market_regimes_data_raw_preprocessing.py": "fb5072f855134d88e57ecfa8796a8fcaad742c2f8da7e32980087dfe118bcac5",
        "tests/test_volatility_market_regimes_input_vertical.py": "c6ec23e344256279dfbb1826e56f0d749c83def91113140c030cdca6717d0336",
        "src/processing_signals/processing/volatility_market_regimes/volatility_market_regimes_feature_builder.py": "5ee3c6fc2546c9700b0134439bd16eeb3f054abe57d8c17aa83f6d171e4e860e",
        "src/processing_signals/processing/volatility_market_regimes/volatility_market_regimes_processor.py": "e2eefc92d9ebdfb6ba9db1eb5a12ed732cd7c062bac1cef3390a52c080c5bdf4",
        "tests/test_volatility_market_regimes_processing.py": "ce8f6d32fd4fa8e0f33b948793b89d4b0f7e487485383d5b1b11e8feb213a205",
        "src/processing_signals/classification/volatility_market_regimes/volatility_market_regimes_classifier.py": "cc0547e18b009d5b04880a14c56bb688a77ee68204229b5a138048bd81fe034e",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
