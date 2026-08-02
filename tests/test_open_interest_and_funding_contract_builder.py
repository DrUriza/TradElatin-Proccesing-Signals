from __future__ import annotations

import copy
import json
import math
import runpy
import sys
from pathlib import Path

import pytest

from processing_signals.classification.open_interest_and_funding.open_interest_and_funding_classifier import (
    classify_open_interest_and_funding,
)
from processing_signals.classification.open_interest_and_funding.open_interest_and_funding_contract_builder import (
    CHART_IDS,
    CONTEXT_FIELDS,
    OPTIONAL_IDS,
    PLACEHOLDER_IDS,
    REQUIRED_IDS,
    TIMEFRAMES,
    OpenInterestAndFundingContractBuilder,
    build_open_interest_and_funding_contract,
)
from processing_signals.processing.open_interest_and_funding.open_interest_and_funding_processor import (
    process_open_interest_and_funding,
)

sys.path.insert(0, str(Path(__file__).parent))
PROCESSING_TEST = Path(__file__).with_name("test_open_interest_and_funding_processing_vertical.py")
BUILDER = Path(__file__).parents[1] / "src/processing_signals/classification/open_interest_and_funding/open_interest_and_funding_contract_builder.py"
ROOT_KEYS = ("family", "stage", "version", "mode", "data_mode", "is_demo", "data_as_of", "context",
             "navigation", "header", "timeframe_selector", "kpis", "charts", "tables", "widgets",
             "drilldowns", "events", "availability", "quality")
KPI_IDS = ("open_interest_usd", "oi_change_24h", "oi_market_cap_ratio", "funding_rate", "funding_8h")
KPI_KEYS = ("id", "status", "reason", "label_key", "value", "secondary_value", "unit", "secondary_unit",
            "timestamp", "timeframe", "classification", "source_paths")
CHART_KEYS = ("id", "status", "reason", "label_key", "timeframe", "chart_type", "series", "axes", "overlays",
              "classification", "source_paths")
SERIES_KEYS = ("id", "status", "reason", "unit", "representation", "points", "source_path")


@pytest.fixture(scope="session")
def frozen_bundle() -> dict:
    input_contract = runpy.run_path(str(PROCESSING_TEST))["_input"]()
    processing = process_open_interest_and_funding(input_contract)
    classification = classify_open_interest_and_funding(processing)
    return {"processing": processing, "classification": classification}


@pytest.fixture()
def bundle(frozen_bundle) -> dict:
    return copy.deepcopy(frozen_bundle)


@pytest.fixture()
def contract(frozen_bundle) -> dict:
    return build_open_interest_and_funding_contract(copy.deepcopy(frozen_bundle))


def _kpi(contract: dict, identifier: str) -> dict:
    return next(item for item in contract["kpis"] if item["id"] == identifier)


def test_functional_and_object_apis_are_identical(bundle):
    direct = build_open_interest_and_funding_contract(bundle)
    assert OpenInterestAndFundingContractBuilder().build(bundle) == direct


@pytest.mark.parametrize("value", [None, [], "x", 1, True, object()])
def test_root_must_be_mapping(value):
    with pytest.raises(ValueError):
        build_open_interest_and_funding_contract(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("keys", [(), ("processing",), ("classification",),
                                  ("processing", "classification", "extra")])
def test_bundle_keys_are_exact(bundle, keys):
    candidate = {key: bundle.get(key, {}) for key in keys}
    with pytest.raises(ValueError):
        build_open_interest_and_funding_contract(candidate)


@pytest.mark.parametrize("name,value", [("processing", []), ("classification", None)])
def test_upstream_contracts_must_be_mappings(bundle, name, value):
    bundle[name] = value
    with pytest.raises(ValueError):
        build_open_interest_and_funding_contract(bundle)


@pytest.mark.parametrize("name,field,value", [
    ("processing", "family", "x"), ("classification", "family", "x"),
    ("processing", "stage", "input"), ("classification", "stage", "processing"),
    ("processing", "version", "1.0"), ("classification", "version", "1.0"),
])
def test_upstream_identity_mismatch_is_value_error(bundle, name, field, value):
    bundle[name][field] = value
    with pytest.raises(ValueError, match="contract_builder_bundle_mismatch"):
        build_open_interest_and_funding_contract(bundle)


@pytest.mark.parametrize("mutation", ["mode", "context", "quality", "snapshots"])
def test_bundle_coherence_is_enforced(bundle, mutation):
    if mutation == "mode":
        bundle["classification"]["mode"] = "recovery"
    elif mutation == "context":
        bundle["classification"]["context"]["asset"] = "ETH"
    elif mutation == "quality":
        bundle["classification"]["quality"]["processing_quality"]["status"] = "invalid"
    else:
        bundle["classification"]["snapshots"]["open_interest_by_exchange"]["records"] = []
    with pytest.raises(ValueError, match="contract_builder_bundle_mismatch"):
        build_open_interest_and_funding_contract(bundle)


def test_context_field_order_and_values_are_exact(contract, frozen_bundle):
    assert tuple(contract["context"]) == CONTEXT_FIELDS
    assert contract["context"] == frozen_bundle["processing"]["context"]


def _runtime_context_bundle(bundle):
    runtime = copy.deepcopy(bundle)
    optional = {"requested_at": 1_800_000_000, "include_snapshots": True,
                "include_confirmations": False}
    runtime["processing"]["context"].update(optional)
    runtime["classification"]["context"] = copy.deepcopy(runtime["processing"]["context"])
    return runtime


def test_legacy_nine_field_context_remains_supported(bundle):
    assert tuple(bundle["processing"]["context"]) == CONTEXT_FIELDS
    assert build_open_interest_and_funding_contract(bundle)["stage"] == "screen_contract"


def test_runtime_context_is_supported_and_projected_to_visual_fields(bundle):
    runtime = _runtime_context_bundle(bundle)
    before = copy.deepcopy(runtime)
    result = build_open_interest_and_funding_contract(runtime)
    assert tuple(result["context"]) == CONTEXT_FIELDS
    assert result["context"] == {field: before["processing"]["context"][field] for field in CONTEXT_FIELDS}
    assert not (set(result["context"]) & {"requested_at", "include_snapshots", "include_confirmations"})
    assert result["data_as_of"] == result["context"]["reference_timestamp"]
    assert runtime == before


@pytest.mark.parametrize("field", ["requested_at", "include_snapshots", "include_confirmations"])
def test_optional_context_mismatch_is_rejected(bundle, field):
    runtime = _runtime_context_bundle(bundle)
    runtime["classification"]["context"][field] = (
        not runtime["processing"]["context"][field] if field != "requested_at" else 1_800_000_001)
    with pytest.raises(ValueError, match="contract_builder_bundle_mismatch:context"):
        build_open_interest_and_funding_contract(runtime)


@pytest.mark.parametrize(("field", "value"), [
    ("requested_at", True), ("requested_at", -1), ("requested_at", "1"),
    ("include_snapshots", 1), ("include_snapshots", None),
    ("include_confirmations", 1), ("include_confirmations", None),
])
def test_optional_context_types_are_exact(bundle, field, value):
    runtime = _runtime_context_bundle(bundle)
    runtime["processing"]["context"][field] = value
    runtime["classification"]["context"] = copy.deepcopy(runtime["processing"]["context"])
    with pytest.raises(ValueError, match="contract_builder_bundle_mismatch:context"):
        build_open_interest_and_funding_contract(runtime)


def test_unknown_context_key_is_rejected(bundle):
    runtime = _runtime_context_bundle(bundle)
    runtime["processing"]["context"]["unexpected"] = "value"
    runtime["classification"]["context"] = copy.deepcopy(runtime["processing"]["context"])
    with pytest.raises(ValueError, match="contract_builder_bundle_mismatch:context"):
        build_open_interest_and_funding_contract(runtime)


@pytest.mark.parametrize("field", CONTEXT_FIELDS)
def test_required_context_field_missing_is_bundle_mismatch(bundle, field):
    bundle["processing"]["context"].pop(field)
    bundle["classification"]["context"] = copy.deepcopy(bundle["processing"]["context"])
    with pytest.raises(ValueError, match="contract_builder_bundle_mismatch:context"):
        build_open_interest_and_funding_contract(bundle)


@pytest.mark.parametrize("field", CONTEXT_FIELDS)
def test_missing_context_field_is_rejected(bundle, field):
    bundle["processing"]["context"].pop(field)
    bundle["classification"]["context"].pop(field)
    with pytest.raises(ValueError, match="context"):
        build_open_interest_and_funding_contract(bundle)


@pytest.mark.parametrize("value", [True, False, -1, 1.5, "1", None])
def test_reference_timestamp_is_exact_nonnegative_int(bundle, value):
    for name in ("processing", "classification"):
        name_context = bundle[name]["context"]
        name_context["reference_timestamp"] = value
    with pytest.raises(ValueError):
        build_open_interest_and_funding_contract(bundle)


@pytest.mark.parametrize(("data_mode", "is_demo"), [("synthetic", False), ("live", True), ("other", False)])
def test_data_mode_demo_coherence(bundle, data_mode, is_demo):
    for name in ("processing", "classification"):
        bundle[name]["context"].update(data_mode=data_mode, is_demo=is_demo)
    with pytest.raises(ValueError):
        build_open_interest_and_funding_contract(bundle)


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
def test_all_six_selected_timeframes(timeframe, frozen_bundle):
    result = build_open_interest_and_funding_contract(frozen_bundle, selected_timeframe=timeframe)
    assert result["timeframe_selector"]["selected_timeframe"] == timeframe
    assert all(item["timeframe"] == timeframe for item in result["kpis"])


@pytest.mark.parametrize("value", [True, 1, 1.0, None, "2h", ""])
def test_invalid_selected_timeframe(value, frozen_bundle):
    with pytest.raises(ValueError, match="contract_builder_selected_timeframe_invalid"):
        build_open_interest_and_funding_contract(frozen_bundle, selected_timeframe=value)  # type: ignore[arg-type]


def test_root_identity_order_and_data_as_of(contract):
    assert tuple(contract) == ROOT_KEYS
    assert (contract["family"], contract["stage"], contract["version"]) == (
        "open_interest_and_funding", "screen_contract", "0.1")
    assert "generated_at" not in {key for key in contract if key != "context"}
    assert contract["data_as_of"] == contract["context"]["reference_timestamp"]


def test_navigation_header_and_selector_are_exact(contract):
    assert contract["navigation"] == {"screen_id": "open_interest_and_funding",
        "route_key": "screens.open_interest_and_funding", "title_key": "screens.open_interest_and_funding.title",
        "legend_key": "screens.open_interest_and_funding.legend"}
    assert contract["header"] == {"title_key": "screens.open_interest_and_funding.title",
        "subtitle_key": "screens.open_interest_and_funding.subtitle", "asset": contract["context"]["asset"],
        "exchange_scope": contract["context"]["exchange_scope"], "demo_badge_key": "common.demo"}
    assert contract["timeframe_selector"] == {"supported_timeframes": list(TIMEFRAMES),
        "default_timeframe": "1h", "selected_timeframe": "1h"}


def test_five_kpis_have_exact_order_schema_and_labels(contract):
    assert tuple(item["id"] for item in contract["kpis"]) == KPI_IDS
    for item in contract["kpis"]:
        assert tuple(item) == KPI_KEYS
        assert item["label_key"] == f"screens.open_interest_and_funding.kpis.{item['id']}"


def test_open_interest_kpi_uses_current_close(contract, frozen_bundle):
    source = frozen_bundle["processing"]["series"]["open_interest_ohlc"]["timeframes"]["1h"]["current"]
    item = _kpi(contract, "open_interest_usd")
    assert (item["value"], item["unit"], item["secondary_value"], item["secondary_unit"]) == (
        source["close"], "USD", None, None)


def test_change_24h_kpi_uses_exact_derived_wrapper_not_interval_delta(contract, frozen_bundle):
    frame = frozen_bundle["processing"]["series"]["open_interest_ohlc"]["timeframes"]["1h"]
    exact = frame["derived"]["oi_change_24h"]["current"]
    delta = frame["derived"]["oi_delta"]["current"]
    item = _kpi(contract, "oi_change_24h")
    assert (item["value"], item["secondary_value"]) == (exact["change_absolute_usd"], exact["change_percent"])
    assert item["value"] != delta["delta_absolute_usd"]
    assert (item["unit"], item["secondary_unit"]) == ("USD", "percent")


def test_funding_kpi_preserves_percentage_points(contract, frozen_bundle):
    expected = frozen_bundle["processing"]["series"]["funding_rate_ohlc"]["timeframes"]["1h"]["current"]["close"]
    item = _kpi(contract, "funding_rate")
    assert (item["value"], item["unit"]) == (expected, "percent_points")


@pytest.mark.parametrize(("identifier", "reason"), [
    ("oi_market_cap_ratio", "market_cap_source_not_configured"),
    ("funding_8h", "cross_exchange_8h_weighting_not_defined"),
])
def test_kpi_placeholders_are_empty(contract, identifier, reason):
    item = _kpi(contract, identifier)
    assert item["status"] == "unavailable" and item["reason"] == reason
    assert all(item[field] is None for field in ("value", "secondary_value", "classification", "timestamp"))


def test_seventeen_charts_have_exact_order_schema_and_labels(contract):
    assert tuple(contract["charts"]) == CHART_IDS
    for identifier, chart in contract["charts"].items():
        assert tuple(chart) == CHART_KEYS
        assert chart["id"] == identifier
        assert chart["label_key"] == f"screens.open_interest_and_funding.charts.{identifier}"
        assert isinstance(chart["series"], list) and isinstance(chart["overlays"], list)


@pytest.mark.parametrize(("identifier", "chart_type", "series_ids", "left", "right"), [
    ("open_interest_line", "line", ("open_interest_close",), "USD", None),
    ("open_interest_interval_delta", "bar", ("delta_absolute_usd",), "USD", None),
    ("funding_rate_line", "line", ("funding_close",), "percent_points", None),
    ("oi_funding_overlay", "multi_line", ("open_interest", "funding_rate"), "USD", "percent_points"),
    ("open_interest_candlestick", "candlestick", ("open_interest_ohlc",), "USD", None),
    ("funding_candlestick", "candlestick", ("funding_ohlc",), "percent_points", None),
    ("bollinger_bands", "multi_line", ("middle", "upper", "lower"), "USD", None),
    ("macd", "oscillator", ("macd", "signal", "histogram"), "USD", None),
    ("adx_di", "oscillator", ("adx_di",), "index_0_100", None),
    ("stochastic", "oscillator", ("stochastic",), "index_0_100", None),
    ("atr", "line", ("atr",), "USD", None), ("cci", "oscillator", ("cci",), "index", None),
    ("oi_roc", "oscillator", ("roc",), "percent", None),
])
def test_calculable_chart_contracts(contract, identifier, chart_type, series_ids, left, right):
    chart = contract["charts"][identifier]
    assert chart["chart_type"] == chart_type
    assert tuple(item["id"] for item in chart["series"]) == series_ids
    assert chart["axes"] == {"x": {"field": "timestamp", "unit": "unix_seconds"},
                              "y": {"left": {"unit": left}, "right": {"unit": right}}}
    assert all(tuple(item) == SERIES_KEYS for item in [*chart["series"], *chart["overlays"]])


def test_visual_point_shapes_and_overlay_independence(contract):
    line = contract["charts"]["open_interest_line"]["series"][0]["points"][0]
    bar = contract["charts"]["open_interest_interval_delta"]["series"][0]["points"][0]
    ohlc = contract["charts"]["open_interest_candlestick"]["series"][0]["points"][0]
    multi = contract["charts"]["adx_di"]["series"][0]["points"][0]
    assert tuple(line) == tuple(bar) == ("timestamp", "value")
    assert tuple(ohlc) == ("timestamp", "open", "high", "low", "close")
    assert tuple(multi) == ("timestamp", "adx", "di_plus", "di_minus")
    overlay = contract["charts"]["oi_funding_overlay"]["series"]
    assert overlay[0]["points"] is not overlay[1]["points"]


def test_candlestick_overlays_and_funding_without_volume(contract):
    oi = contract["charts"]["open_interest_candlestick"]
    funding = contract["charts"]["funding_candlestick"]
    assert tuple(item["id"] for item in oi["overlays"]) == ("sma_20", "sma_50", "sma_100", "sma_200")
    assert funding["overlays"] == []
    assert all("volume" not in point for point in funding["series"][0]["points"])


def test_macd_and_multivalue_chart_contracts(contract):
    macd = contract["charts"]["macd"]["series"]
    assert tuple(item["representation"] for item in macd) == ("line", "line", "bar")
    assert contract["charts"]["adx_di"]["classification"].keys() == {
        "oi_trend_strength", "directional_index_relation"}
    assert contract["charts"]["stochastic"]["series"][0]["representation"] == "multi_value"


@pytest.mark.parametrize(("identifier", "reason"), [
    ("mfi", "historical_volume_series_not_available"), ("oi_market_cap", "market_cap_source_not_configured"),
    ("oi_vs_price", "price_source_not_available_in_processing_contract"),
    ("contract_type_split", "dated_futures_open_interest_not_separated_by_current_sources"),
])
def test_chart_placeholders_are_empty(contract, identifier, reason):
    chart = contract["charts"][identifier]
    assert (chart["chart_type"], chart["status"], chart["reason"]) == ("placeholder", "unavailable", reason)
    assert chart["series"] == [] and chart["overlays"] == [] and chart["classification"] is None


@pytest.mark.parametrize("identifier", CHART_IDS)
def test_each_chart_has_closed_type_paths_and_status(identifier, contract):
    chart = contract["charts"][identifier]
    assert chart["chart_type"] in {"line", "bar", "candlestick", "multi_line", "oscillator", "placeholder"}
    assert chart["status"] in {"available", "partial", "unavailable", "invalid"}
    assert all(isinstance(path, str) for path in chart["source_paths"])


@pytest.mark.parametrize("metric", ["open_interest_ohlc", "funding_rate_ohlc"])
def test_history_without_current_is_partial(bundle, metric):
    bundle["processing"]["series"][metric]["timeframes"]["1h"]["current"] = None
    result = build_open_interest_and_funding_contract(bundle)
    identifier = "open_interest_line" if metric == "open_interest_ohlc" else "funding_rate_line"
    assert (result["charts"][identifier]["status"], result["charts"][identifier]["reason"]) == (
        "partial", "current_unavailable_history_available")


@pytest.mark.parametrize(("metric", "identifiers"), [
    ("open_interest_ohlc", ("open_interest_line", "open_interest_candlestick")),
    ("funding_rate_ohlc", ("funding_rate_line", "funding_candlestick")),
])
def test_empty_history_and_current_preserve_upstream_unavailable(metric, identifiers, bundle):
    frame = bundle["processing"]["series"][metric]["timeframes"]["1h"]
    frame.update(status="unavailable", reason="upstream_history_unavailable", current=None, records=[])
    result = build_open_interest_and_funding_contract(bundle)
    for identifier in identifiers:
        chart = result["charts"][identifier]
        assert (chart["status"], chart["reason"]) == ("unavailable", "upstream_history_unavailable")
        assert chart["series"] == [] and chart["overlays"] == [] and chart["classification"] is None


def test_technical_table_schema_columns_rows_and_macd(contract):
    table = contract["tables"]["oi_technical_indicators"]
    assert tuple(table) == ("id", "status", "reason", "label_key", "timeframe", "columns", "rows", "source_paths")
    assert table["columns"] == ["indicator", "value", "secondary_values", "unit", "classification_state", "status", "reason", "timestamp"]
    expected = ("sma_20", "sma_50", "sma_100", "sma_200", "bollinger_percent_b", "macd", "adx", "di_plus",
                "di_minus", "stochastic_k", "stochastic_d", "atr", "cci", "oi_roc", "mfi")
    assert tuple(row["id"] for row in table["rows"]) == expected
    assert all(isinstance(row["secondary_values"], dict) for row in table["rows"])
    macd = next(row for row in table["rows"] if row["id"] == "macd")
    assert tuple(macd["secondary_values"]) == ("signal", "histogram")
    assert all(row["secondary_values"] == {} for row in table["rows"] if row["id"] != "macd")
    assert table["status"] == "available"


@pytest.mark.parametrize("identifier", ["sma_20", "sma_50", "sma_100", "sma_200", "bollinger_percent_b",
    "macd", "adx", "di_plus", "di_minus", "stochastic_k", "stochastic_d", "atr", "cci", "oi_roc", "mfi"])
def test_each_technical_row_has_exact_schema(identifier, contract):
    row = next(item for item in contract["tables"]["oi_technical_indicators"]["rows"] if item["id"] == identifier)
    assert tuple(row) == ("id", "status", "reason", "value", "secondary_values", "unit", "timestamp", "timeframe",
                          "classification_state", "source_path")
    assert isinstance(row["secondary_values"], dict)


def test_two_widgets_have_exact_schemas(contract):
    assert tuple(contract["widgets"]) == ("oi_funding_state", "provider_availability")
    assert tuple(contract["widgets"]["oi_funding_state"]) == ("id", "status", "reason", "label_key", "timeframe",
        "timestamp", "open_interest_change_state", "funding_state", "quadrant_state", "source_paths")
    assert tuple(contract["widgets"]["provider_availability"]) == (
        "id", "status", "reason", "label_key", "rows", "comparisons", "source_paths")


def test_provider_rows_order_and_comparisons(contract):
    widget = contract["widgets"]["provider_availability"]
    assert tuple(f"{row['metric']}.{row['provider']}" for row in widget["rows"]) == (
        "open_interest.cryptoquant", "open_interest.glassnode", "funding_rate.cryptoquant", "funding_rate.glassnode")
    assert widget["comparisons"] == {"status": "unavailable", "reason": "provider_scope_not_proven_comparable",
                                      "provider_state": "provider_unavailable"}


def test_three_drilldowns_columns_metadata_and_order(contract, frozen_bundle):
    assert tuple(contract["drilldowns"]) == ("open_interest_by_exchange", "funding_rate_by_exchange", "options_open_interest")
    specs = {
        "open_interest_by_exchange": (("exchange", "open_interest_usd", "open_interest_change_percent_24h"),
            ("invalid_records", "exchange_count", "current_total_usd", "reported_changes")),
        "funding_rate_by_exchange": (("exchange", "margin_type", "funding_rate_percent", "next_funding_timestamp"),
            ("invalid_records", "stablecoin_margin_records", "token_margin_records", "exchange_count", "next_funding_timestamps")),
        "options_open_interest": (("exchange", "open_interest_usd", "open_interest_contracts"),
            ("invalid_records", "current_options_open_interest_usd", "current_options_contracts")),
    }
    for identifier, (columns, metadata) in specs.items():
        item = contract["drilldowns"][identifier]
        assert tuple(item["columns"]) == columns and tuple(item["metadata"]) == metadata
        assert [row["exchange"] for row in item["records"]] == [
            row["exchange"] for row in frozen_bundle["processing"]["snapshots"][identifier]["records"]]
    assert contract["drilldowns"]["funding_rate_by_exchange"]["aggregate_record"] is None


@pytest.mark.parametrize("field", ["stablecoin_margin_records", "token_margin_records"])
def test_funding_nested_metadata_projects_exact_allowlist(field, bundle):
    approved = ("exchange", "margin_type", "funding_rate_percent", "next_funding_timestamp")
    snapshot = bundle["processing"]["snapshots"]["funding_rate_by_exchange"]
    snapshot[field][0].update(EXTRA="leak", unexpected=1, raw_payload={"secret": True})
    bundle["classification"]["snapshots"] = copy.deepcopy(bundle["processing"]["snapshots"])
    rows = build_open_interest_and_funding_contract(bundle)["drilldowns"]["funding_rate_by_exchange"]["metadata"][field]
    assert isinstance(rows, list) and tuple(rows[0]) == approved


def test_events_schema_filter_order_limit_and_markers(contract):
    events = contract["events"]
    assert tuple(events) == ("id", "status", "reason", "timeframe", "order", "limit", "total_available", "items",
                             "event_markers", "source_path")
    assert events["id"] == "recent_events" and events["limit"] == 50
    assert len(events["items"]) <= 50 and all(item["timeframe"] == "1h" for item in events["items"])
    ordering = [(-item["timestamp"], item["event_type"], item["event_id"]) for item in events["items"]]
    assert ordering == sorted(ordering)
    marker_ids = {item["event_id"] for item in events["event_markers"]}
    assert marker_ids == {item["event_id"] for item in events["items"] if item["status"] != "invalid"}


@pytest.mark.parametrize("value", [[], None, "invalid"])
def test_incompatible_interpreted_events_are_isolated(value, bundle):
    bundle["classification"]["interpreted_events"] = value
    result = build_open_interest_and_funding_contract(bundle)
    events = result["events"]
    assert events["status"] == "invalid" and events["reason"] == "contract_builder_input_invalid:interpreted_events"
    assert events["total_available"] == 0 and events["items"] == [] and events["event_markers"] == []
    assert result["quality"]["status"] == "partial"
    assert "optional_invalid:events.recent_events" in result["quality"]["warnings"]


def test_incompatible_interpreted_events_propagate_safe_upstream_reason(bundle):
    bundle["classification"]["interpreted_events"] = {"status": "invalid", "reason": "upstream_events_invalid"}
    assert build_open_interest_and_funding_contract(bundle)["events"]["reason"] == "upstream_events_invalid"


def test_availability_exact_categories_and_ids(contract):
    availability = contract["availability"]
    assert tuple(availability) == ("required", "optional", "passthrough", "placeholders")
    assert tuple(availability["required"]) == REQUIRED_IDS
    assert tuple(availability["optional"]) == OPTIONAL_IDS
    assert tuple(availability["passthrough"]) == ("snapshots", "confirmations", "events")
    assert tuple(availability["placeholders"]) == PLACEHOLDER_IDS


def test_passthrough_snapshots_propagate_highest_precedence_reason(bundle):
    snapshot = bundle["processing"]["snapshots"]["open_interest_by_exchange"]
    snapshot.update(status="partial", reason="snapshot_partial_reason")
    bundle["classification"]["snapshots"] = copy.deepcopy(bundle["processing"]["snapshots"])
    item = build_open_interest_and_funding_contract(bundle)["availability"]["passthrough"]["snapshots"]
    assert item == {"status": "partial", "reason": "snapshot_partial_reason", "source_paths": ["snapshots"]}


def test_passthrough_confirmations_propagate_widget_reason(bundle):
    payload = bundle["classification"]["confirmations"]["open_interest"]["cryptoquant"]
    payload.update(status="partial", reason="confirmation_partial_reason")
    item = build_open_interest_and_funding_contract(bundle)["availability"]["passthrough"]["confirmations"]
    assert (item["status"], item["reason"]) == ("partial", "confirmation_partial_reason")


def test_passthrough_events_propagate_isolated_invalid_reason(bundle):
    bundle["classification"]["interpreted_events"] = None
    result = build_open_interest_and_funding_contract(bundle)
    assert result["availability"]["passthrough"]["events"] == {
        "status": "invalid", "reason": "contract_builder_input_invalid:interpreted_events",
        "source_paths": ["interpreted_events"]}


def test_every_availability_entry_obeys_status_reason_invariant(contract):
    for category in contract["availability"].values():
        for item in category.values():
            if item["status"] == "available":
                assert item["reason"] is None
            else:
                assert isinstance(item["reason"], str) and item["reason"]


def test_quality_exact_schema_sources_and_statuses(contract, frozen_bundle):
    quality = contract["quality"]
    assert tuple(quality) == ("status", "contract_complete", "data_complete", "source_quality", "builder_quality",
                              "required_statuses", "optional_statuses", "placeholder_statuses", "warnings", "errors")
    assert quality["source_quality"]["processing"] == frozen_bundle["processing"]["quality"]
    assert quality["source_quality"]["classification"] == frozen_bundle["classification"]["quality"]
    assert tuple(quality["builder_quality"]) == ("status", "warnings", "errors")
    assert quality["status"] == "ok" and quality["data_complete"] is True and quality["contract_complete"] is True
    assert quality["warnings"] == sorted(set(quality["warnings"]))
    assert quality["errors"] == sorted(set(quality["errors"]))
    assert all(value == "unavailable" for value in quality["placeholder_statuses"].values())


@pytest.mark.parametrize("identifier", PLACEHOLDER_IDS)
def test_each_placeholder_is_unavailable_without_warning(identifier, contract):
    assert contract["quality"]["placeholder_statuses"][identifier] == "unavailable"
    assert all(identifier not in warning for warning in contract["quality"]["warnings"])


def test_deep_immutability_output_decoupling_and_determinism(bundle):
    before = copy.deepcopy(bundle)
    first = build_open_interest_and_funding_contract(bundle)
    second = build_open_interest_and_funding_contract(copy.deepcopy(bundle))
    assert bundle == before and first == second
    assert first["context"] is not bundle["processing"]["context"]
    assert first["drilldowns"]["open_interest_by_exchange"]["records"] is not bundle["processing"]["snapshots"]["open_interest_by_exchange"]["records"]
    first["context"]["asset"] = "changed"
    assert bundle == before


def test_strict_json_and_negative_zero_normalization(bundle):
    frame = bundle["processing"]["series"]["funding_rate_ohlc"]["timeframes"]["1h"]
    frame["current"]["close"] = -0.0
    frame["records"][-1]["close"] = -0.0
    output = build_open_interest_and_funding_contract(bundle)
    assert math.copysign(1, _kpi(output, "funding_rate")["value"]) == 1
    json.dumps(output, ensure_ascii=False, allow_nan=False, sort_keys=False)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), {"x"}, b"x", object()])
def test_non_json_values_are_rejected(bundle, bad):
    bundle["processing"]["context"]["generated_at"] = bad
    bundle["classification"]["context"]["generated_at"] = bad
    with pytest.raises(ValueError):
        build_open_interest_and_funding_contract(bundle)


def test_source_has_no_prohibited_imports_or_behaviour():
    source = BUILDER.read_text(encoding="utf-8").lower()
    for token in ("import pandas", "import numpy", "processing.math", "requests", "os.environ", "datetime.now",
                  "time.time", "uuid", "random", "default=str", "bullish", "bearish", "buy", "sell"):
        assert token not in source
    assert "open(" not in source and "write_text" not in source and "write_bytes" not in source


def test_no_runtime_or_main_vertical_writes_exist():
    source = BUILDER.read_text(encoding="utf-8")
    assert "runtime/contracts" not in source
    assert "screen_contract_export" not in source
    assert "processing_signals.main" not in source
