from __future__ import annotations

import copy
import json
import math

import pytest

from processing_signals.classification.on_chain_miners.on_chain_miners_classifier import (
    DEFAULT_RESERVE_TREND_WINDOW,
    MPI_HIGH_PRESSURE_MIN,
    MPI_LOW_PRESSURE_MAX,
    NUPL_BELIEF_DENIAL_MAX,
    NUPL_CAPITULATION_MAX,
    NUPL_HOPE_FEAR_MAX,
    NUPL_OPTIMISM_ANXIETY_MAX,
    RESERVE_TREND_EPSILON_PERCENT_PER_DAY,
    SOPR_BREAKEVEN_EPSILON,
    OnChainMinersClassifier,
    classify_miner_pressure,
    classify_net_position,
    classify_nupl_phase,
    classify_on_chain_miners,
    classify_reserve_trend,
    classify_sopr_regime,
)
from processing_signals.processing.on_chain_miners.on_chain_miners_processor import process_on_chain_miners
from test_on_chain_miners_processing_vertical import input_contract


CLASSIFICATION_IDS = {"miner_pressure", "reserve_trend", "net_position", "sopr_regime", "nupl_phase"}
ALLOWED_TOKENS     = {"positive", "negative", "warning", "neutral", "unavailable", "invalid"}
FORBIDDEN_KEYS     = {"widgets", "charts", "kpis", "selectors", "badges", "screen", "contract", "events",
                      "sopr_7d_calculated", "reserve_delta_calculated", "slope_calculated", "r_squared_calculated",
                      "coverage_ratio_calculated", "hashrate_eh_s_calculated", "difficulty_t_calculated"}


@pytest.fixture
def processing():
    return process_on_chain_miners(input_contract())


@pytest.fixture
def classified(processing):
    return classify_on_chain_miners(processing)


def _keys(value):
    keys = set()
    if isinstance(value, dict):
        keys.update(value)
        for child in value.values():
            keys.update(_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_keys(child))
    return keys


def _walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_output_structure_and_identity(classified):
    assert set(classified) == {"family", "stage", "mode", "context", "classifications", "quality"}
    assert classified["family"] == "on_chain_miners"
    assert classified["stage"] == "classification"
    assert set(classified["classifications"]) == CLASSIFICATION_IDS


@pytest.mark.parametrize("mode", ["bootstrap", "incremental", "recovery"])
def test_mode_and_context_are_preserved(mode):
    source = process_on_chain_miners(input_contract(mode=mode))
    result = classify_on_chain_miners(source)
    assert result["mode"] == mode
    assert result["context"]["data_mode"] == source["context"]["data_mode"]
    assert result["context"]["is_demo"] == source["context"]["is_demo"]


def test_processing_is_not_mutated(processing):
    original = copy.deepcopy(processing)
    classify_on_chain_miners(processing)
    assert processing == original


def test_output_has_no_contract_or_presentation_keys(classified):
    assert not (_keys(classified) & FORBIDDEN_KEYS)


@pytest.mark.parametrize(("value", "state", "signal", "label", "reason"), [
    (-0.000001, "low_selling_pressure", "bullish", "LOW", "mpi_below_zero"),
    (0.0, "moderate_selling_pressure", "neutral", "MODERATE", "mpi_between_zero_and_two"),
    (0.000001, "moderate_selling_pressure", "neutral", "MODERATE", "mpi_between_zero_and_two"),
    (1.0, "moderate_selling_pressure", "neutral", "MODERATE", "mpi_between_zero_and_two"),
    (1.999999, "moderate_selling_pressure", "neutral", "MODERATE", "mpi_between_zero_and_two"),
    (2.0, "moderate_selling_pressure", "neutral", "MODERATE", "mpi_between_zero_and_two"),
    (2.000001, "high_selling_pressure", "bearish", "HIGH", "mpi_above_two"),
])
def test_miner_pressure_boundaries(value, state, signal, label, reason):
    basis = {"status": "available", "current": {"status": "available", "timestamp": 10, "value": value, "unit": "z_score"},
             "previous": {"timestamp": 9, "value": 100}, "change_1d": -999, "unit": "z_score"}
    result = classify_miner_pressure(basis)
    assert (result["state"], result["signal"], result["display_label"], result["reason"]) == (state, signal, label, reason)
    assert result["status"] == "available" and result["display_color_token"] in ALLOWED_TOKENS
    assert result["source"]["previous"] == basis["previous"]
    assert result["source"]["change_1d"] == -999


def test_miner_pressure_thresholds_are_public():
    result = classify_miner_pressure({"status": "available", "current": {"status": "available", "timestamp": 1, "value": 1, "unit": "z_score"}})
    assert result["thresholds"] == {"low_pressure_max": MPI_LOW_PRESSURE_MAX, "high_pressure_min": MPI_HIGH_PRESSURE_MIN}


@pytest.mark.parametrize("status", ["unavailable", "invalid"])
def test_miner_pressure_absence_is_not_neutral(status):
    result = classify_miner_pressure({"status": status, "current": {"status": status, "value": None}})
    assert result["status"] == status
    assert result["state"] is result["signal"] is None


def test_miner_pressure_partial_stays_partial():
    result = classify_miner_pressure({"status": "partial", "current": {"status": "available", "timestamp": 1, "value": -1, "unit": "z_score"}})
    assert result["status"] == "partial" and result["state"] == "low_selling_pressure"


def _trend(value=0.0, status="available"):
    return {"status": status, "windows": {"30d": {"status": status, "last_timestamp": 30, "first_timestamp": 1,
            "slope_btc_per_day": 999, "normalized_slope_percent_per_day": value, "r_squared": 0.123,
            "coverage_ratio": 0.9, "net_change_btc": -55, "percent_change": 77, "observations": 27,
            "total_missing_days": 3, "history_complete": status == "available"}}}


@pytest.mark.parametrize(("value", "state", "signal", "label", "token", "reason"), [
    (-0.001001, "decreasing", "bearish", "DECREASING", "negative", "normalized_slope_below_negative_threshold"),
    (-0.001, "stable", "neutral", "STABLE", "neutral", "normalized_slope_inside_stable_band"),
    (-0.000999, "stable", "neutral", "STABLE", "neutral", "normalized_slope_inside_stable_band"),
    (0.0, "stable", "neutral", "STABLE", "neutral", "normalized_slope_inside_stable_band"),
    (0.000999, "stable", "neutral", "STABLE", "neutral", "normalized_slope_inside_stable_band"),
    (0.001, "stable", "neutral", "STABLE", "neutral", "normalized_slope_inside_stable_band"),
    (0.001001, "increasing", "bullish", "INCREASING", "positive", "normalized_slope_above_positive_threshold"),
])
def test_reserve_trend_thresholds(value, state, signal, label, token, reason):
    result = classify_reserve_trend(_trend(value))
    assert (result["status"], result["state"], result["signal"]) == ("available", state, signal)
    assert (result["display_label"], result["display_color_token"], result["reason"]) == (label, token, reason)
    assert result["source"]["window"] == DEFAULT_RESERVE_TREND_WINDOW


def test_reserve_trend_preserves_received_regression_values():
    result = classify_reserve_trend(_trend(0.002))
    assert {key: result["source"][key] for key in ("slope_btc_per_day", "r_squared", "coverage_ratio", "total_missing_days")} == {
        "slope_btc_per_day": 999, "r_squared": 0.123, "coverage_ratio": 0.9, "total_missing_days": 3}
    assert result["state"] == "increasing"


def test_reserve_trend_public_threshold():
    assert classify_reserve_trend(_trend())["thresholds"] == {
        "epsilon_percent_per_day": RESERVE_TREND_EPSILON_PERCENT_PER_DAY, "window": "30d"}


def test_reserve_trend_partial_with_slope_is_classified():
    result = classify_reserve_trend(_trend(0.002, "partial"))
    assert result["status"] == "partial" and result["state"] == "increasing"
    assert "reserve_trend_basis_partial" in result["warnings"]


@pytest.mark.parametrize(("status", "value", "expected"), [("unavailable", None, "unavailable"), ("invalid", None, "invalid")])
def test_reserve_trend_without_valid_slope_has_no_state(status, value, expected):
    result = classify_reserve_trend(_trend(value, status))
    assert result["status"] == expected and result["state"] is None and result["signal"] is None


@pytest.mark.parametrize(("value", "state", "signal", "label"), [(10, "net_accumulation", "bullish", "ACCUMULATION"),
                                                                   (-5, "net_distribution", "bearish", "DISTRIBUTION"),
                                                                   (0, "balanced", "neutral", "BALANCED")])
def test_net_position_sign(value, state, signal, label):
    basis  = {"status": "available", "current": {"status": "available", "timestamp": 5, "value": value, "unit": "BTC/day"}}
    result = classify_net_position(basis)
    assert (result["state"], result["signal"], result["display_label"]) == (state, signal, label)
    assert result["source"] == {"feature_id": "net_position_basis", "timestamp": 5, "value": value, "unit": "BTC/day"}


@pytest.mark.parametrize("status", ["unavailable", "invalid"])
def test_net_position_absence_is_not_balanced(status):
    result = classify_net_position({"status": status, "current": {"status": status, "value": None}})
    assert result["status"] == status and result["state"] is None and result["signal"] is None


@pytest.mark.parametrize(("value", "state", "signal", "label", "token", "reason"), [
    (0.998999, "loss", "bearish", "LOSS", "negative", "sopr_below_breakeven_band"),
    (0.999, "breakeven", "neutral", "BREAKEVEN", "neutral", "sopr_inside_breakeven_band"),
    (0.999001, "breakeven", "neutral", "BREAKEVEN", "neutral", "sopr_inside_breakeven_band"),
    (1.0, "breakeven", "neutral", "BREAKEVEN", "neutral", "sopr_inside_breakeven_band"),
    (1.000999, "breakeven", "neutral", "BREAKEVEN", "neutral", "sopr_inside_breakeven_band"),
    (1.001, "breakeven", "neutral", "BREAKEVEN", "neutral", "sopr_inside_breakeven_band"),
    (1.001001, "profit", "bullish", "PROFIT", "positive", "sopr_above_breakeven_band"),
])
def test_sopr_regime_boundaries(value, state, signal, label, token, reason):
    raw = {"status": "available", "timestamp": 5, "value": 99, "unit": "ratio"}
    result = classify_sopr_regime({"status": "available", "current": {"status": "available", "timestamp": 5, "value": value, "unit": "ratio"},
                                   "raw_sopr_current": raw})
    assert (result["status"], result["state"], result["signal"]) == ("available", state, signal)
    assert (result["display_label"], result["display_color_token"], result["reason"]) == (label, token, reason)
    assert result["source"]["raw_sopr_current"] == raw


def test_sopr_regime_thresholds_are_public():
    basis = {"status": "available", "current": {"status": "available", "timestamp": 1, "value": 1, "unit": "ratio"}}
    assert classify_sopr_regime(basis)["thresholds"] == {"center": 1.0, "epsilon": SOPR_BREAKEVEN_EPSILON}


@pytest.mark.parametrize("status", ["unavailable", "invalid"])
def test_missing_sopr_7d_does_not_use_raw(status):
    basis = {"status": status, "current": {"status": status, "value": None},
             "raw_sopr_current": {"status": "available", "timestamp": 1, "value": 2, "unit": "ratio"}}
    result = classify_sopr_regime(basis)
    assert result["state"] is None and result["signal"] is None


def test_sopr_partial_stays_partial():
    basis = {"status": "partial", "current": {"status": "available", "timestamp": 1, "value": 1.01, "unit": "ratio"}}
    assert classify_sopr_regime(basis)["status"] == "partial"


def test_processing_invalid_bounds_all_classifications(processing):
    processing["quality"]["status"] = "invalid"
    result = classify_on_chain_miners(processing)
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None
    assert all(item["status"] == "invalid" and item["state"] is None for item in result["classifications"].values())


def test_processing_partial_never_improves_to_ok(processing):
    processing["quality"]["status"] = "partial"
    result = classify_on_chain_miners(processing)
    assert result["quality"]["status"] == "partial"
    assert result["quality"]["warnings"]


@pytest.mark.parametrize(("field", "message", "expected"), [("warnings", "source_late", "processing_warning:source_late"),
                                                               ("errors", "source_bad", "processing_error:source_bad")])
def test_processing_messages_are_propagated(processing, field, message, expected):
    processing["quality"][field] = [message]
    result = classify_on_chain_miners(processing)
    assert expected in result["quality"][field]


@pytest.mark.parametrize(("feature", "classification_id", "status", "container", "prefix"), [
    ("miner_pressure_basis", "miner_pressure", "partial", "warnings", "classification_basis_partial"),
    ("sopr_regime_basis", "sopr_regime", "unavailable", "warnings", "classification_basis_unavailable"),
    ("net_position_basis", "net_position", "invalid", "errors", "classification_basis_invalid"),
])
def test_basis_status_has_explicit_global_explanation(processing, feature, classification_id, status, container, prefix):
    processing["features"][feature]["status"] = status
    if status != "partial":
        processing["features"][feature]["current"] = {"status": status, "value": None}
    result = classify_on_chain_miners(processing)
    assert f"{prefix}:{classification_id}" in result["quality"][container]
    if status == "unavailable":
        assert classification_id in result["quality"]["missing_fields"]


def test_data_as_of_uses_minimum_source_timestamp(processing):
    features = processing["features"]
    features["miner_pressure_basis"]["current"]["timestamp"] = 100
    features["reserve_trend"]["windows"]["30d"]["last_timestamp"] = 200
    features["net_position_basis"]["current"]["timestamp"] = 300
    features["sopr_regime_basis"]["current"]["timestamp"] = 400
    processing["quality"]["data_as_of"] = 500
    processing["context"]["reference_timestamp"] = 1
    processing["context"]["execution_timestamp"] = 2
    assert classify_on_chain_miners(processing)["quality"]["data_as_of"] == 100


def test_data_as_of_is_capped_by_processing(processing):
    processing["quality"]["data_as_of"] = 1
    result = classify_on_chain_miners(processing)
    assert result["quality"]["data_as_of"] == 1
    assert "classification_data_as_of_capped_by_processing" in result["quality"]["warnings"]


def test_missing_source_timestamp_makes_data_as_of_null(processing):
    processing["features"]["sopr_regime_basis"]["current"]["timestamp"] = None
    result = classify_on_chain_miners(processing)
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None


def test_incremental_changes_when_feature_current_changes(processing):
    before = classify_on_chain_miners(processing)
    processing["mode"] = "incremental"
    processing["features"]["miner_pressure_basis"]["current"]["value"] = -0.1
    after = classify_on_chain_miners(processing)
    assert before["classifications"]["miner_pressure"]["state"] != after["classifications"]["miner_pressure"]["state"]


def test_recovery_can_restore_unavailable_basis(processing):
    basis = processing["features"]["sopr_regime_basis"]
    saved = copy.deepcopy(basis)
    basis.update({"status": "unavailable", "current": {"status": "unavailable", "value": None}})
    assert classify_on_chain_miners(processing)["classifications"]["sopr_regime"]["status"] == "unavailable"
    processing["mode"] = "recovery"
    processing["features"]["sopr_regime_basis"] = saved
    assert classify_on_chain_miners(processing)["classifications"]["sopr_regime"]["status"] == "available"


def test_classification_consumes_features_not_series(processing):
    before = classify_on_chain_miners(processing)
    processing["series"] = {"mpi": {"records": [{"timestamp": 1, "value": -999}]}, "sopr": {"records": []},
                            "miner_reserve_btc": {"records": [{"timestamp": 1, "value": -999}]}}
    after = classify_on_chain_miners(processing)
    assert before == after


def test_strict_json_and_python_scalars_only(classified):
    assert json.dumps(classified, ensure_ascii=False, allow_nan=False)
    for value in _walk(classified):
        assert not isinstance(value, float) or math.isfinite(value)
        assert not (isinstance(value, float) and value == 0 and math.copysign(1, value) < 0)
        assert isinstance(value, (dict, list, str, int, float, bool, type(None)))


@pytest.mark.parametrize("classification_id", sorted(CLASSIFICATION_IDS))
def test_every_classification_has_required_fields(classification_id, classified):
    assert {"status", "state", "signal", "display_label", "display_color_token", "reason", "source", "thresholds"} <= set(
        classified["classifications"][classification_id])


def test_tokens_labels_and_no_hex_colors(classified):
    for item in classified["classifications"].values():
        assert item["display_color_token"] in ALLOWED_TOKENS
        assert item["display_label"] == item["display_label"].upper()
        assert not item["display_color_token"].startswith("#")


@pytest.mark.parametrize(("field", "value", "fragment"), [("family", "other", "family_must_be"), ("stage", "input", "stage_must_be"),
                                                              ("mode", "other", "mode_must_be"), ("context", [], "context_must_be"),
                                                              ("series", [], "series_must_be"), ("features", [], "features_must_be"),
                                                              ("quality", [], "quality_must_be")])
def test_incompatible_top_level_contract_is_invalid(processing, field, value, fragment):
    processing[field] = value
    result = classify_on_chain_miners(processing)
    assert result["quality"]["status"] == "invalid"
    assert any(fragment in error for error in result["quality"]["errors"])


@pytest.mark.parametrize("feature_id", ["reserve_trend", "miner_pressure_basis", "sopr_regime_basis", "net_position_basis"])
def test_missing_required_feature_is_invalid(processing, feature_id):
    del processing["features"][feature_id]
    assert classify_on_chain_miners(processing)["quality"]["status"] == "invalid"


@pytest.mark.parametrize(("feature", "unit"), [("miner_pressure_basis", "ratio"), ("net_position_basis", "BTC"),
                                                 ("sopr_regime_basis", "z_score")])
def test_incompatible_units_are_invalid(processing, feature, unit):
    processing["features"][feature]["current"]["unit"] = unit
    assert classify_on_chain_miners(processing)["quality"]["status"] == "invalid"


@pytest.mark.parametrize(("feature", "value"), [("miner_pressure_basis", math.nan), ("net_position_basis", math.inf),
                                                  ("sopr_regime_basis", -math.inf)])
def test_non_finite_consumed_values_are_invalid(processing, feature, value):
    processing["features"][feature]["current"]["value"] = value
    result = classify_on_chain_miners(processing)
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None


def test_public_facade_and_class_are_equivalent(processing):
    assert classify_on_chain_miners(processing) == OnChainMinersClassifier(processing).run()


@pytest.mark.parametrize(("feature", "status"), [("reserve_trend", "unknown"), ("sopr_regime_basis", "ok"),
                                                   ("net_position_basis", "missing")])
def test_unknown_basis_status_is_invalid(processing, feature, status):
    processing["features"][feature]["status"] = status
    assert classify_on_chain_miners(processing)["quality"]["status"] == "invalid"


@pytest.mark.parametrize("field", ["warnings", "errors"])
def test_non_string_processing_message_is_invalid(processing, field):
    processing["quality"][field] = [{"not": "a string"}]
    result = classify_on_chain_miners(processing)
    assert result["quality"]["status"] == "invalid"


def test_negative_zero_is_normalized_without_mutating_processing(processing):
    processing["features"]["net_position_basis"]["current"]["value"] = -0.0
    original = copy.deepcopy(processing)
    result = classify_on_chain_miners(processing)
    value = result["classifications"]["net_position"]["source"]["value"]
    assert value == 0.0 and math.copysign(1, value) > 0
    assert processing == original


def _set_path(mapping, path, value):
    target = mapping
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value


@pytest.mark.parametrize(("classification_id", "processing_path", "source_path", "value", "error_path"), [
    ("miner_pressure", ("miner_pressure_basis", "change_1d"), ("change_1d",), math.nan, "miner_pressure.source.change_1d"),
    ("miner_pressure", ("miner_pressure_basis", "change_1d"), ("change_1d",), math.inf, "miner_pressure.source.change_1d"),
    ("miner_pressure", ("miner_pressure_basis", "previous", "value"), ("previous", "value"), math.nan, "miner_pressure.source.previous.value"),
    ("miner_pressure", ("miner_pressure_basis", "previous", "value"), ("previous", "value"), math.inf, "miner_pressure.source.previous.value"),
    ("miner_pressure", ("miner_pressure_basis", "previous", "timestamp"), ("previous", "timestamp"), 1.0, "miner_pressure.source.previous.timestamp"),
    ("miner_pressure", ("miner_pressure_basis", "previous", "value"), ("previous", "value"), object(), "miner_pressure.source.previous.value"),
    ("sopr_regime", ("sopr_regime_basis", "raw_sopr_current", "value"), ("raw_sopr_current", "value"), math.nan,
     "sopr_regime.source.raw_sopr_current.value"),
    ("sopr_regime", ("sopr_regime_basis", "raw_sopr_current", "value"), ("raw_sopr_current", "value"), math.inf,
     "sopr_regime.source.raw_sopr_current.value"),
    ("sopr_regime", ("sopr_regime_basis", "raw_sopr_current", "timestamp"), ("raw_sopr_current", "timestamp"), 1.0,
     "sopr_regime.source.raw_sopr_current.timestamp"),
    ("reserve_trend", ("reserve_trend", "windows", "30d", "first_value_btc"), ("first_value_btc",), math.nan,
     "reserve_trend.source.first_value_btc"),
    ("reserve_trend", ("reserve_trend", "windows", "30d", "first_value_btc"), ("first_value_btc",), math.inf,
     "reserve_trend.source.first_value_btc"),
    ("reserve_trend", ("reserve_trend", "windows", "30d", "last_value_btc"), ("last_value_btc",), -math.inf,
     "reserve_trend.source.last_value_btc"),
    ("reserve_trend", ("reserve_trend", "windows", "30d", "r_squared"), ("r_squared",), math.nan,
     "reserve_trend.source.r_squared"),
    ("reserve_trend", ("reserve_trend", "windows", "30d", "coverage_ratio"), ("coverage_ratio",), math.inf,
     "reserve_trend.source.coverage_ratio"),
    ("reserve_trend", ("reserve_trend", "windows", "30d", "first_timestamp"), ("first_timestamp",), 1.0,
     "reserve_trend.source.first_timestamp"),
    ("net_position", ("net_position_basis", "current", "value"), ("value",), math.nan, "net_position.source.value"),
])
def test_auxiliary_invalid_source_values_are_local_and_json_safe(
        processing, classification_id, processing_path, source_path, value, error_path):
    _set_path(processing["features"], processing_path, value)
    result = classify_on_chain_miners(processing)
    item = result["classifications"][classification_id]
    published = item["source"]
    for part in source_path:
        published = published[part]
    assert published is None
    assert item["status"] == "invalid" and item["state"] is None and item["signal"] is None
    assert item["reason"] == "invalid_source_payload"
    assert any(error_path in error for error in item["errors"])
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None
    assert f"classification_source_invalid:{classification_id}" in result["quality"]["errors"]
    assert any(error.startswith(f"classification_error:{classification_id}:") and error_path in error for error in result["quality"]["errors"])
    assert json.dumps(result, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize(("container", "classification_id", "feature_id"), [
    ("warnings", "miner_pressure", "miner_pressure_basis"),
    ("errors", "net_position", "net_position_basis"),
])
def test_non_string_feature_messages_are_omitted_and_invalidate(processing, container, classification_id, feature_id):
    processing["features"][feature_id][container] = ["valid", {"invalid": True}, "valid"]
    result = classify_on_chain_miners(processing)
    item = result["classifications"][classification_id]
    assert item["status"] == "invalid" and item["state"] is None and item["signal"] is None
    assert any(f"invalid_source_message:{classification_id}.source.{container}[1]" == error for error in item["errors"])
    expected = f"feature_{'warning' if container == 'warnings' else 'error'}:{classification_id}:valid"
    assert item[container].count(expected) == 1
    assert json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_non_string_window_message_is_omitted_and_invalidates_reserve_trend(processing):
    processing["features"]["reserve_trend"]["windows"]["30d"]["warnings"] = ["valid", object(), "valid"]
    result = classify_on_chain_miners(processing)
    item = result["classifications"]["reserve_trend"]
    assert item["status"] == "invalid" and item["source"]["warnings"] == ["valid"]
    assert "invalid_source_message:reserve_trend.source.warnings[1]" in item["errors"]
    assert json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_reserve_trend_uses_only_30d_window(processing):
    windows = processing["features"]["reserve_trend"]["windows"]
    windows["30d"]["normalized_slope_percent_per_day"] = 0.002
    windows["7d"]["normalized_slope_percent_per_day"] = -999
    windows["90d"]["normalized_slope_percent_per_day"] = -999
    before = classify_on_chain_miners(processing)["classifications"]["reserve_trend"]
    windows["7d"]["normalized_slope_percent_per_day"] = 999
    windows["90d"]["normalized_slope_percent_per_day"] = 999
    after = classify_on_chain_miners(processing)["classifications"]["reserve_trend"]
    assert before == after and after["state"] == "increasing"


@pytest.mark.parametrize(("feature_id", "classification_id"), [
    ("miner_pressure_basis", "miner_pressure"),
    ("reserve_trend", "reserve_trend"),
    ("net_position_basis", "net_position"),
    ("sopr_regime_basis", "sopr_regime"),
])
def test_partial_without_valid_current_never_becomes_neutral(processing, feature_id, classification_id):
    basis = processing["features"][feature_id]
    basis["status"] = "partial"
    if feature_id == "reserve_trend":
        basis["windows"]["30d"].update({"status": "partial", "normalized_slope_percent_per_day": None})
    else:
        basis["current"] = {"status": "unavailable", "timestamp": None, "value": None, "unit": basis.get("unit")}
    result = classify_on_chain_miners(processing)
    item = result["classifications"][classification_id]
    assert item["status"] in {"partial", "unavailable", "invalid"}
    assert item["state"] is None and item["signal"] is None
    assert item["state"] not in {"moderate_selling_pressure", "stable", "balanced", "breakeven"}
    assert result["quality"]["status"] != "ok"
    assert result["quality"]["warnings"] or result["quality"]["errors"] or result["quality"]["missing_fields"]


@pytest.mark.parametrize(("feature_id", "classification_id", "container", "prefix"), [
    ("miner_pressure_basis", "miner_pressure", "warnings", "feature_warning:miner_pressure:"),
    ("miner_pressure_basis", "miner_pressure", "errors", "feature_error:miner_pressure:"),
    ("reserve_trend", "reserve_trend", "warnings", "feature_warning:reserve_trend:"),
    ("sopr_regime_basis", "sopr_regime", "warnings", "feature_warning:sopr_regime:"),
    ("net_position_basis", "net_position", "errors", "feature_error:net_position:"),
])
def test_feature_messages_are_prefixed_stable_and_deduplicated(processing, feature_id, classification_id, container, prefix):
    processing["features"][feature_id][container] = ["first", "first", "second"]
    item = classify_on_chain_miners(processing)["classifications"][classification_id]
    assert item[container][-2:] == [f"{prefix}first", f"{prefix}second"]


@pytest.mark.parametrize(("container", "prefix"), [("warnings", "feature_window_warning:reserve_trend:30d:"),
                                                      ("errors", "feature_window_error:reserve_trend:30d:")])
def test_reserve_window_messages_are_prefixed_and_deduplicated(processing, container, prefix):
    processing["features"]["reserve_trend"]["windows"]["30d"][container] = ["first", "first", "second"]
    item = classify_on_chain_miners(processing)["classifications"]["reserve_trend"]
    assert item[container][-2:] == [f"{prefix}first", f"{prefix}second"]


def test_reference_and_execution_timestamps_do_not_affect_data_as_of(processing):
    source_timestamp = processing["quality"]["data_as_of"]
    processing["context"]["reference_timestamp"] = source_timestamp + 100 * 86_400
    processing["context"]["execution_timestamp"] = source_timestamp + 200 * 86_400
    assert classify_on_chain_miners(processing)["quality"]["data_as_of"] == source_timestamp


@pytest.mark.parametrize(("classification_id", "feature_id"), [
    ("miner_pressure", "miner_pressure_basis"), ("reserve_trend", "reserve_trend"),
    ("net_position", "net_position_basis"), ("sopr_regime", "sopr_regime_basis"),
])
def test_source_and_threshold_mappings_have_independent_identity(processing, classification_id, feature_id):
    result = classify_on_chain_miners(processing)["classifications"][classification_id]
    basis = processing["features"][feature_id]
    assert result["source"] is not basis
    assert result["thresholds"] is not basis
    if classification_id == "miner_pressure":
        assert result["source"]["previous"] is not basis["previous"]
    elif classification_id == "sopr_regime":
        assert result["source"]["raw_sopr_current"] is not basis["raw_sopr_current"]
    elif classification_id == "reserve_trend":
        assert result["source"] is not basis["windows"]["30d"]


def test_final_serialization_fallback_never_returns_contaminated_output(processing):
    processing["context"]["generated_at"] = object()
    result = classify_on_chain_miners(processing)
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None
    assert result["quality"]["errors"] == ["classification_output_serialization_failed:TypeError"]
    assert all(item["status"] == "invalid" and item["state"] is None for item in result["classifications"].values())
    assert json.dumps(result, ensure_ascii=False, allow_nan=False)


def _nupl_basis(value=0.60, *, status="available"):
    return {"feature_id": "nupl_phase_basis", "status": status,
            "current": {"status": "available", "timestamp": 1_700_000_000, "value": value, "price_usd": 60_000.0, "unit": "ratio"},
            "previous": {"status": "available", "timestamp": 1_699_913_600, "value": 0.59, "price_usd": 59_000.0, "unit": "ratio", "reason": None},
            "change_1d": 0.01, "warnings": [], "errors": [],
            "metadata": {"previous_policy": "exact_previous_calendar_day", "classification_pending": True}}


@pytest.mark.parametrize(("value", "state", "signal", "label", "token", "reason"), [
    (-0.000001, "capitulation", "bearish", "CAPITULATION", "negative", "nupl_below_zero"),
    (0.0, "hope_fear", "neutral", "HOPE / FEAR", "warning", "nupl_between_zero_and_point_twenty_five"),
    (0.249999, "hope_fear", "neutral", "HOPE / FEAR", "warning", "nupl_between_zero_and_point_twenty_five"),
    (0.25, "optimism_anxiety", "bullish", "OPTIMISM / ANXIETY", "positive", "nupl_between_point_twenty_five_and_point_fifty"),
    (0.499999, "optimism_anxiety", "bullish", "OPTIMISM / ANXIETY", "positive", "nupl_between_point_twenty_five_and_point_fifty"),
    (0.50, "belief_denial", "neutral", "BELIEF / DENIAL", "warning", "nupl_between_point_fifty_and_point_seventy_five"),
    (0.749999, "belief_denial", "neutral", "BELIEF / DENIAL", "warning", "nupl_between_point_fifty_and_point_seventy_five"),
    (0.75, "euphoria_greed", "bearish", "EUPHORIA / GREED", "negative", "nupl_at_or_above_point_seventy_five"),
    (1.0, "euphoria_greed", "bearish", "EUPHORIA / GREED", "negative", "nupl_at_or_above_point_seventy_five"),
])
def test_nupl_phase_boundaries_and_semantics(value, state, signal, label, token, reason):
    result = classify_nupl_phase(_nupl_basis(value))
    assert (result["state"], result["signal"], result["display_label"], result["display_color_token"], result["reason"]) == (state, signal, label, token, reason)


def test_nupl_thresholds_are_complete_and_explicit():
    result = classify_nupl_phase(_nupl_basis())
    assert result["thresholds"] == {"capitulation_max": NUPL_CAPITULATION_MAX, "hope_fear_max": NUPL_HOPE_FEAR_MAX,
                                     "optimism_anxiety_max": NUPL_OPTIMISM_ANXIETY_MAX, "belief_denial_max": NUPL_BELIEF_DENIAL_MAX}
    assert result["thresholds"] == {"capitulation_max": 0.0, "hope_fear_max": 0.25, "optimism_anxiety_max": 0.5, "belief_denial_max": 0.75}


def test_nupl_source_preserves_previous_change_and_price_without_recalculation():
    basis = _nupl_basis(0.60)
    basis["previous"]["value"] = -100
    basis["change_1d"] = 999
    result = classify_nupl_phase(basis)
    assert result["state"] == "belief_denial"
    assert result["source"]["previous"] == basis["previous"] and result["source"]["change_1d"] == 999
    assert result["source"]["price_usd"] == basis["current"]["price_usd"]


def test_nupl_partial_with_valid_current_remains_partial():
    result = classify_nupl_phase(_nupl_basis(status="partial"))
    assert result["status"] == "partial" and result["state"] == "belief_denial"
    assert "classification_basis_partial:nupl_phase" in result["warnings"]


@pytest.mark.parametrize("status", ["unavailable", "invalid"])
def test_nupl_absent_basis_never_generates_phase(status):
    basis = _nupl_basis(status=status)
    basis["current"] = {"status": status, "value": None, "unit": "ratio"}
    result = classify_nupl_phase(basis)
    assert result["status"] == status and result["state"] is None and result["signal"] is None
    assert result["display_label"] == status.upper() and result["display_color_token"] == status


def test_nupl_partial_without_current_has_no_artificial_phase():
    basis = _nupl_basis(status="partial")
    basis["current"] = {"status": "unavailable", "value": None, "unit": "ratio"}
    result = classify_nupl_phase(basis)
    assert result["status"] == "partial" and result["state"] is None and result["signal"] is None
    assert result["warnings"] and result["reason"] == "nupl_current_unavailable"


@pytest.mark.parametrize(("field", "value", "reason"), [("unit", "percent", "incompatible_nupl_unit"),
                                                            ("timestamp", 1.5, "invalid_nupl_timestamp"),
                                                            ("value", math.nan, "nupl_value_not_finite"),
                                                            ("price_usd", math.inf, "nupl_price_not_finite")])
def test_nupl_invalid_current_fields_are_invalid_and_json_safe(field, value, reason):
    basis = _nupl_basis()
    basis["current"][field] = value
    result = classify_nupl_phase(basis)
    assert result["status"] == "invalid" and result["state"] is None and result["signal"] is None
    assert result["reason"] in {reason, "invalid_source_payload"}
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_nupl_invalid_change_is_sanitized_and_invalidates_global_quality(processing):
    processing["features"]["nupl_phase_basis"]["change_1d"] = math.nan
    result = classify_on_chain_miners(processing)
    item = result["classifications"]["nupl_phase"]
    assert item["status"] == "invalid" and item["source"]["change_1d"] is None
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_non_string_nupl_basis_key_invalidates_without_exception(processing):
    processing["features"]["nupl_phase_basis"][1] = "bad"
    result = classify_on_chain_miners(processing)
    assert result["quality"]["status"] == "invalid"
    assert any(error.startswith("non_string_source_key:processing.features.nupl_phase_basis") for error in result["quality"]["errors"])
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_processing_invalid_invalidates_exactly_five_classifications(processing):
    processing["quality"]["status"] = "invalid"
    result = classify_on_chain_miners(processing)
    assert set(result["classifications"]) == CLASSIFICATION_IDS and len(result["classifications"]) == 5
    assert all(item["status"] == "invalid" and item["state"] is None for item in result["classifications"].values())
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None


def test_classification_quality_availability_has_exactly_five_keys(classified):
    assert set(classified["quality"]["availability"]) == CLASSIFICATION_IDS
    assert all(classified["quality"]["availability"][name] == classified["classifications"][name]["status"] for name in CLASSIFICATION_IDS)


def test_data_as_of_includes_nupl_timestamp(processing):
    earlier = processing["features"]["nupl_phase_basis"]["current"]["timestamp"] - 10 * 86_400
    processing["features"]["nupl_phase_basis"]["current"]["timestamp"] = earlier
    processing["features"]["nupl_phase_basis"]["previous"]["timestamp"] = earlier - 86_400
    assert classify_on_chain_miners(processing)["quality"]["data_as_of"] == earlier


def test_missing_nupl_timestamp_makes_data_as_of_null(processing):
    processing["features"]["nupl_phase_basis"]["current"]["timestamp"] = None
    result = classify_on_chain_miners(processing)
    assert result["classifications"]["nupl_phase"]["status"] == "invalid"
    assert result["quality"]["data_as_of"] is None


def test_nupl_classification_uses_basis_not_processing_series(processing):
    before = classify_on_chain_miners(processing)["classifications"]["nupl_phase"]
    processing["series"]["nupl"] = {"records": [{"timestamp": 0, "value": -999}], "current": {"value": -999}}
    after = classify_on_chain_miners(processing)["classifications"]["nupl_phase"]
    assert after == before


def test_nupl_reference_execution_and_generated_at_do_not_affect_classification(processing):
    before = classify_on_chain_miners(processing)
    processing["context"].update({"reference_timestamp": 1, "execution_timestamp": 2, "generated_at": "changed"})
    after = classify_on_chain_miners(processing)
    assert after["classifications"] == before["classifications"] and after["quality"]["data_as_of"] == before["quality"]["data_as_of"]


def test_nupl_processing_contract_remains_immutable(processing):
    before = copy.deepcopy(processing)
    classify_on_chain_miners(processing)
    assert processing == before


def test_nupl_adds_no_recalculation_or_drilldown_fields(classified):
    forbidden = {"nupl_phase_calculated", "nupl_change_calculated", "nupl_average", "nupl_percentile", "widgets", "charts", "screen", "contract", "events"}
    assert forbidden.isdisjoint(_keys(classified))
    assert set(classified["classifications"]) == CLASSIFICATION_IDS


def test_nupl_normal_and_invalid_outputs_are_strict_json(processing):
    assert json.dumps(classify_on_chain_miners(processing), ensure_ascii=False, allow_nan=False)
    processing["features"]["nupl_phase_basis"]["current"]["price_usd"] = math.inf
    invalid = classify_on_chain_miners(processing)
    assert invalid["quality"]["status"] == "invalid"
    assert json.dumps(invalid, ensure_ascii=False, allow_nan=False)
