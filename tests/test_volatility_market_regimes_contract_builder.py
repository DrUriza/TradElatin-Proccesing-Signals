from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from processing_signals.classification.volatility_market_regimes.volatility_market_regimes_classifier       import classify_volatility_market_regimes
from processing_signals.classification.volatility_market_regimes.volatility_market_regimes_contract_builder import (
    DISPLAY_RANGE_OPTIONS,
    build_market_regime_table,
    build_positioning_ratio_chart,
    build_spread_7d_kpi,
    build_visible_regime_events,
    build_volatility_market_regimes_screen,
    validate_runtime_context,
    validate_volatility_market_regimes_builder_inputs,
)
from tests.test_volatility_market_regimes_classification import _processing


ROOT    = Path(__file__).parents[1]
RUNTIME = {"data_mode": "synthetic", "is_demo": True, "generated_at": "2027-01-15T08:00:00Z", "updated_at": "2027-01-15T08:01:00+00:00"}


def _contracts(mode: str = "bootstrap") -> tuple[dict, dict]:
    processing     = _processing(mode)
    classification = classify_volatility_market_regimes(processing)
    return processing, classification


def _screen(mode: str = "bootstrap", runtime: dict | None = None, selected_range: str = "7d") -> dict:
    processing, classification = _contracts(mode)
    return build_volatility_market_regimes_screen(processing, classification, runtime_context=runtime or RUNTIME, selected_range=selected_range)


@pytest.mark.parametrize("side,field,value", [
    ("processing", "family", "other"), ("processing", "stage", "other"), ("processing", "version", "9"),
    ("classification", "family", "other"), ("classification", "stage", "other"), ("classification", "version", "9"),
])
def test_contract_identity_validation(side, field, value):
    processing, classification = _contracts()
    target = processing if side == "processing" else classification
    target[field] = value
    with pytest.raises(ValueError):
        validate_volatility_market_regimes_builder_inputs(processing, classification, RUNTIME)
    assert build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)["quality"]["status"] == "invalid"


@pytest.mark.parametrize("field,value", [
    ("mode", "incremental"), ("reference_timestamp", 1), ("input_execution_timestamp", 1),
    ("asset", "ETH"), ("symbol", "ETHUSDT"), ("exchange", "Other"), ("base_interval", "4h"),
])
def test_cross_contract_mismatches_are_invalid(field, value):
    processing, classification = _contracts()
    if field == "mode":
        classification[field] = value
    else:
        classification["context"][field] = value
    result = build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)
    assert result["quality"]["status"] == "invalid"
    assert result["quality"]["errors"]


@pytest.mark.parametrize("runtime", [
    {"data_mode": "synthetic", "is_demo": False, "generated_at": "2027-01-01T00:00:00Z", "updated_at": "2027-01-01T00:00:00Z"},
    {"data_mode": "live", "is_demo": True, "generated_at": "2027-01-01T00:00:00Z", "updated_at": "2027-01-01T00:00:00Z"},
    {"data_mode": "live", "is_demo": False, "generated_at": "2027-01-01T00:00:00", "updated_at": "2027-01-01T00:00:00Z"},
])
def test_runtime_context_rejects_incoherent_or_naive_values(runtime):
    with pytest.raises(ValueError):
        validate_runtime_context(runtime)


def test_runtime_live_and_synthetic_badges():
    validate_runtime_context(RUNTIME)
    live = {"data_mode": "live", "is_demo": False, "generated_at": "2027-01-15T08:00:00Z", "updated_at": "2027-01-15T08:00:00Z"}
    validate_runtime_context(live)
    assert _screen()["badges"] == [{"badge_id": "demo", "text": "DEMO", "status": "active"}]
    assert _screen(runtime=live)["badges"] == []


def test_root_selector_context_and_no_wrapper():
    screen = _screen(selected_range="4h")
    assert list(screen) == ["family", "screen", "schema_version", "context", "badges", "selectors", "kpis", "charts", "tables", "widgets", "events", "quality"]
    assert screen["screen"] == "volatility_market_regimes" and screen["schema_version"] == "0.1.0"
    selector = screen["selectors"]["display_range"]
    assert selector["options"] == list(DISPLAY_RANGE_OPTIONS) and selector["selected"] == "4h"
    assert screen["context"]["default_display_range"] == "7d" and screen["context"]["base_interval"] == "1h"
    assert screen["context"]["data_as_of"] == max(window["end_timestamp"] for window in screen["context"]["range_windows"].values())


def test_unknown_range_returns_controlled_invalid_contract():
    assert _screen(selected_range="90d")["quality"] == {
        "status": "invalid", "contract_complete": False, "data_complete": False, "availability": {},
        "missing_fields": [], "warnings": [], "errors": ["selected_range:invalid"],
    }


def test_kpis_copy_and_format_upstream_values_in_stable_order():
    processing, classification = _contracts()
    daily  = classification["classifications"]["daily_regimes"]
    spread = classification["classifications"]["spread_context"]
    daily["current"]["confidence_score"] = 0.734
    daily["current_persistence_days"] = 1
    spread.update(value=3.26, spread_state="realized_above_implied")
    screen = build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)
    items  = screen["kpis"]["items"]
    assert [item["metric_id"] for item in items] == ["current_regime", "confidence", "spread_7d", "persistence"]
    assert items[0]["value"] == daily["current"]["regime"]
    assert items[1]["value"] == 0.734 and items[1]["display_value"] == "73%"
    assert items[2]["value"] == 3.26 and items[2]["display_value"] == "+3.3 vol pts"
    assert items[3]["display_value"] == "1 day"
    daily["current_persistence_days"] = 2
    assert build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)["kpis"]["items"][3]["display_value"] == "2 days"


def test_unavailable_kpis_show_placeholder_and_spread_is_not_recalculated():
    processing, classification = _contracts()
    classification["classifications"]["daily_regimes"].update(current=None, current_persistence_days=None, status="unavailable", reason="none")
    classification["classifications"]["spread_context"].update(value=None, status="unavailable", reason="no_pairs")
    items = build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)["kpis"]["items"]
    assert all(item["display_value"] == "--" for item in items)
    source = {"status": "partial", "reason": "coverage", "value": -7.14, "spread_state": "realized_below_implied", "unit": "volatility_points",
              "basis": "realized_minus_implied", "records_used": 5, "coverage": 0.25, "window_start_timestamp": 1, "window_end_timestamp": 2}
    assert build_spread_7d_kpi(source)["value"] == -7.14


def test_positioning_chart_joins_semantics_without_reclassification():
    processing, classification = _contracts()
    raw      = processing["features"]["positioning"]["records"][-1]
    semantic = classification["classifications"]["positioning"]["records"][-1]
    semantic["positioning_state"] = "short_bias"
    chart = build_positioning_ratio_chart(processing["features"]["positioning"], classification["classifications"]["positioning"])
    assert chart["records"][-1]["long_short_ratio"] == raw["long_short_ratio"]
    assert chart["records"][-1]["positioning_state"] == "short_bias"
    assert chart["reference_lines"] == [{"value": 1.0, "label": "Balanced"}]
    classification["classifications"]["positioning"]["records"].pop()
    chart = build_positioning_ratio_chart(processing["features"]["positioning"], classification["classifications"]["positioning"])
    assert chart["status"] == "partial" and chart["records"][-1]["positioning_state"] is None


def test_charts_copy_hourly_daily_current_and_distribution_without_fill_or_recalculation():
    processing, classification = _contracts()
    screen       = build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)
    volatility   = screen["charts"]["volatility_comparison"]
    timeline     = screen["charts"]["regime_timeline"]
    distribution = screen["charts"]["regime_distribution"]
    source       = processing["features"]["volatility_comparison"]
    assert volatility["records"][-1]["spread_volatility_points"] == source["records"][-1]["spread_volatility_points"]
    assert volatility["current"] == source["current"]
    assert timeline["records"][-1]["confidence_score"] == classification["classifications"]["daily_regimes"]["records"][-1]["confidence_score"]
    assert distribution["classified_days"] == classification["summaries"]["regime_distribution"]["full_history"]["classified_days"]
    assert "probability" not in json.dumps(distribution)


def test_table_has_stable_rows_and_copies_episode_statistics():
    _, classification = _contracts()
    table = build_market_regime_table(classification["summaries"]["regime_statistics"])
    assert [row["regime"] for row in table["rows"]] == ["low_vol", "normal", "high_vol"]
    assert table["rows"][1]["episode_count"] == classification["summaries"]["regime_statistics"][1]["episode_count"]
    assert "probability" not in json.dumps(table)


def test_source_widget_has_only_real_providers_and_internal():
    providers = [item["provider_id"] for item in _screen()["widgets"]["source_status"]["items"]]
    assert providers == ["coinglass", "glassnode", "deribit", "internal"]
    assert "cryptoquant" not in providers


def test_history_is_visually_truncated_without_degrading_available_status():
    processing, classification = _contracts()
    base = processing["features"]["positioning"]["records"][0]
    processing["features"]["positioning"]["records"] = [{**base, "timestamp": base["timestamp"] + index * 3600} for index in range(800)]
    semantics = classification["classifications"]["positioning"]["records"][0]
    classification["classifications"]["positioning"]["records"] = [{**semantics, "timestamp": base["timestamp"] + index * 3600} for index in range(800)]
    chart = build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)["charts"]["positioning_ratio"]
    assert chart["records_available"] == 800 and chart["records_returned"] <= 721 and chart["history_truncated"] is True
    assert chart["status"] == "available"
    timeline = _screen()["charts"]["regime_timeline"]
    assert timeline["records_returned"] <= 30 and timeline["records_available"] >= timeline["records_returned"]


def test_events_are_copied_once_visible_and_timeline_has_only_references():
    screen = _screen()
    events = screen["events"]
    assert len(events["by_id"]) == len(events["regime_transition_ids"]) == len(set(events["regime_transition_ids"]))
    assert all(event_id in events["by_id"] for row in screen["charts"]["regime_timeline"]["records"] for event_id in row["event_ids"])
    assert all(isinstance(event_id, str) for row in screen["charts"]["regime_timeline"]["records"] for event_id in row["event_ids"])


def test_broken_duplicate_or_mismatched_event_references_are_invalid():
    processing, classification = _contracts()
    events   = classification["interpreted_events"]
    event_id = "volatility_market_regimes:1:regime_transition:normal:high_vol"
    events["regime_transition_ids"] = [event_id]
    events["by_id"] = {}
    assert build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)["quality"]["status"] == "invalid"
    events["by_id"] = {event_id: {"event_id": event_id, "timestamp": 1}}
    events["regime_transition_ids"] = [event_id, event_id]
    assert build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)["quality"]["status"] == "invalid"


def test_visible_event_filter_preserves_ids_and_excludes_outside_window():
    event_id = "e"
    source   = {"by_id": {event_id: {"event_id": event_id, "timestamp": 10}}, "regime_transition_ids": [event_id]}
    assert build_visible_regime_events(source, 11, 20) == {"by_id": {}, "regime_transition_ids": []}
    assert build_visible_regime_events(source, 1, 20)["by_id"][event_id]["event_id"] == event_id


def test_quality_partial_and_invalid_follow_visual_availability():
    screen = _screen()
    assert screen["quality"]["contract_complete"] is True and screen["quality"]["status"] == "partial"
    processing, classification = _contracts()
    classification["classifications"]["spread_context"]["status"] = "invalid"
    assert build_volatility_market_regimes_screen(processing, classification, runtime_context=RUNTIME)["quality"]["status"] == "invalid"


def test_builder_is_immutable_deterministic_and_strict_json():
    processing, classification = _contracts()
    runtime   = copy.deepcopy(RUNTIME)
    originals = copy.deepcopy((processing, classification, runtime))
    first     = build_volatility_market_regimes_screen(processing, classification, runtime_context=runtime)
    second    = build_volatility_market_regimes_screen(processing, classification, runtime_context=runtime)
    assert first == second and (processing, classification, runtime) == originals
    first["charts"]["positioning_ratio"]["records"][0]["long_short_ratio"] = 0
    assert (processing, classification, runtime) == originals
    json.dumps(second, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False)


def test_modes_with_same_data_only_differ_operationally_upstream():
    screens = []
    for mode in ("bootstrap", "incremental", "recovery"):
        screen = _screen(mode)
        screens.append(screen)
    assert screens[0] == screens[1] == screens[2]


def test_no_bundles_secrets_trading_language_or_probability():
    text = json.dumps(_screen()).lower()
    for forbidden in ('"processing"', '"classification"', '"input"', "raw_response", "api_key", "probability", '"buy"', '"sell"', "bullish", "bearish", "#"):
        assert forbidden not in text


def test_ast_has_no_upstream_recalculation_or_forbidden_imports():
    path    = ROOT / "src/processing_signals/classification/volatility_market_regimes/volatility_market_regimes_contract_builder.py"
    tree    = ast.parse(path.read_text(encoding="utf-8"))
    imports = [ast.unparse(node) for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert not any("processing_signals.input" in item or "processing.math" in item for item in imports)
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for forbidden in ("calculate_spread", "calculate_confidence", "calculate_persistence", "calculate_percentile", "classify_positioning", "build_transition_events"):
        assert forbidden not in names


def test_frozen_hashes_are_unchanged():
    expected = {
        "src/processing_signals/input/volatility_market_regimes/volatility_market_regimes_data_raw_extract.py": "ba816680d9c1f39d69eb587395402a0658b53c9b97b5b2585fa8b92a05624f6c",
        "src/processing_signals/input/volatility_market_regimes/volatility_market_regimes_data_raw_preprocessing.py": "fb5072f855134d88e57ecfa8796a8fcaad742c2f8da7e32980087dfe118bcac5",
        "tests/test_volatility_market_regimes_input_vertical.py": "c6ec23e344256279dfbb1826e56f0d749c83def91113140c030cdca6717d0336",
        "src/processing_signals/processing/volatility_market_regimes/volatility_market_regimes_feature_builder.py": "5ee3c6fc2546c9700b0134439bd16eeb3f054abe57d8c17aa83f6d171e4e860e",
        "src/processing_signals/processing/volatility_market_regimes/volatility_market_regimes_processor.py": "e2eefc92d9ebdfb6ba9db1eb5a12ed732cd7c062bac1cef3390a52c080c5bdf4",
        "tests/test_volatility_market_regimes_processing.py": "ce8f6d32fd4fa8e0f33b948793b89d4b0f7e487485383d5b1b11e8feb213a205",
        "src/processing_signals/classification/volatility_market_regimes/volatility_market_regimes_classifier.py": "cc0547e18b009d5b04880a14c56bb688a77ee68204229b5a138048bd81fe034e",
        "tests/test_volatility_market_regimes_classification.py": "0626c7ef4b14cf7422ac1b459fcb2deacfd67abf62c52413e578b8e56c522b95",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
