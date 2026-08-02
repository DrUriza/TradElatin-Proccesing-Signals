from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy

import pytest

from processing_signals.classification.open_interest_and_funding.open_interest_and_funding_classifier import (
    classify_open_interest_and_funding,
)
from processing_signals.classification.open_interest_and_funding.open_interest_and_funding_contract_builder import (
    CHART_IDS,
    CONTEXT_FIELDS,
    SCREEN_SCHEMA,
    SCREEN_VERSION,
    TIMEFRAMES,
    build_open_interest_and_funding_contract,
)
from processing_signals.processing.open_interest_and_funding.open_interest_and_funding_processor import (
    process_open_interest_and_funding,
)


PROCESSING_TEST = Path(__file__).with_name("test_open_interest_and_funding_processing_vertical.py")
ROOT = ("schema", "screen", "stage", "mode", "context", "timeframe_selector", "operational_status",
        "kpis", "charts", "tables", "widgets", "drilldowns", "events", "availability", "quality")


@pytest.fixture(scope="session")
def frozen_bundle() -> dict:
    source = runpy.run_path(str(PROCESSING_TEST))["_input"]()
    processing = process_open_interest_and_funding(source)
    return {"processing": processing, "classification": classify_open_interest_and_funding(processing)}


@pytest.fixture()
def bundle(frozen_bundle) -> dict:
    return copy.deepcopy(frozen_bundle)


@pytest.fixture()
def contract(frozen_bundle) -> dict:
    return build_open_interest_and_funding_contract(copy.deepcopy(frozen_bundle))


def test_complete_visual_root_and_identity(contract):
    assert tuple(contract) == ROOT
    assert contract["schema"] == {"id": SCREEN_SCHEMA, "version": SCREEN_VERSION}
    assert contract["screen"] == {"id": "open_interest_and_funding", "route": "/open-interest-and-funding",
                                  "title": "OPEN INTEREST & FUNDING", "family": "open_interest_and_funding"}
    assert contract["stage"] == "screen_contract"


def test_context_and_operational_status_are_hmi_ready(contract, frozen_bundle):
    source = frozen_bundle["processing"]["context"]
    assert tuple(contract["context"]) == (*CONTEXT_FIELDS, "data_as_of", "presentation_default_timeframe")
    assert all(contract["context"][field] == source[field] for field in CONTEXT_FIELDS)
    assert contract["context"]["data_as_of"] == source["reference_timestamp"]
    assert contract["operational_status"] == {
        "data_mode": source["data_mode"], "is_demo": source["is_demo"],
        "quality_status": contract["quality"]["status"], "connection_status": "not_reported",
        "cache_status": "not_reported", "generated_at": source["generated_at"],
        "data_as_of": source["reference_timestamp"],
    }


def test_timeframe_selector_keeps_all_oi_timeframes(contract):
    selector = contract["timeframe_selector"]
    assert tuple(item["id"] for item in selector["options"]) == TIMEFRAMES
    assert selector["default"] == selector["selected"] == "1h"


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
def test_each_selected_timeframe(timeframe, frozen_bundle):
    result = build_open_interest_and_funding_contract(frozen_bundle, selected_timeframe=timeframe)
    assert result["timeframe_selector"]["selected"] == timeframe
    assert result["context"]["presentation_default_timeframe"] == timeframe
    assert all(chart["selected_timeframe"] == timeframe for chart in result["charts"].values())


@pytest.mark.parametrize("value", [None, True, 1, "", "2h"])
def test_invalid_timeframe(value, frozen_bundle):
    with pytest.raises(ValueError, match="contract_builder_selected_timeframe_invalid"):
        build_open_interest_and_funding_contract(frozen_bundle, selected_timeframe=value)


def test_five_visual_kpis_are_keyed_and_complete(contract):
    assert tuple(contract["kpis"]) == (
        "open_interest_usd", "oi_change_24h", "oi_market_cap_ratio", "funding_rate", "funding_8h")
    for identifier, item in contract["kpis"].items():
        assert item["kpi_id"] == identifier and item["title"]
        assert "status" in item and "value" in item and "source_paths" in item


def test_all_seventeen_charts_publish_six_timeframes(contract):
    assert tuple(contract["charts"]) == CHART_IDS
    for identifier, chart in contract["charts"].items():
        assert chart["chart_id"] == identifier and chart["title"] and chart["subtitle"]
        assert tuple(chart["series_by_timeframe"]) == TIMEFRAMES
        assert chart["current"]["status"] == chart["status"]
        for timeframe, payload in chart["series_by_timeframe"].items():
            assert payload["timeframe"] == timeframe
            assert isinstance(payload["series"], list) and isinstance(payload["overlays"], list)


def test_historical_fixture_produces_visible_chart_points(contract):
    charts = contract["charts"]
    for identifier in ("open_interest_line", "funding_rate_line", "open_interest_candlestick"):
        counts = [sum(len(series["points"]) for series in payload["series"])
                  for payload in charts[identifier]["series_by_timeframe"].values()]
        assert max(counts) > 20


def test_tables_widgets_drilldowns_events_and_availability_remain_published(contract):
    assert len(contract["tables"]["oi_technical_indicators"]["rows"]) == 15
    assert tuple(contract["widgets"]) == ("oi_funding_state", "provider_availability")
    assert tuple(contract["drilldowns"]) == (
        "open_interest_by_exchange", "funding_rate_by_exchange", "options_open_interest")
    assert contract["events"]["id"] == "recent_events"
    assert tuple(contract["availability"]) == ("required", "optional", "passthrough", "placeholders")


def test_runtime_context_is_allowed_but_not_published(bundle):
    optional = {"requested_at": "2027-01-15T08:00:00Z", "include_snapshots": True,
                "include_confirmations": False}
    bundle["processing"]["context"].update(optional)
    bundle["classification"]["context"] = copy.deepcopy(bundle["processing"]["context"])
    before = copy.deepcopy(bundle)
    result = build_open_interest_and_funding_contract(bundle)
    assert not (set(optional) & set(result["context"]))
    assert bundle == before


@pytest.mark.parametrize("value", [1, True, None, "", "   "])
def test_requested_at_invalid_values_are_rejected(value, bundle):
    bundle["processing"]["context"]["requested_at"] = value
    bundle["classification"]["context"] = copy.deepcopy(bundle["processing"]["context"])
    with pytest.raises(ValueError, match="contract_builder_bundle_mismatch:context"):
        build_open_interest_and_funding_contract(bundle)


def test_context_mismatch_and_unknown_keys_are_rejected(bundle):
    bundle["processing"]["context"]["unexpected"] = True
    bundle["classification"]["context"] = copy.deepcopy(bundle["processing"]["context"])
    with pytest.raises(ValueError, match="contract_builder_bundle_mismatch:context"):
        build_open_interest_and_funding_contract(bundle)


@pytest.mark.parametrize("value", [None, [], "x", 1, True])
def test_root_must_be_mapping(value):
    with pytest.raises(ValueError):
        build_open_interest_and_funding_contract(value)


def test_bundle_keys_are_exact(bundle):
    bundle["input"] = {}
    with pytest.raises(ValueError, match="bundle.keys"):
        build_open_interest_and_funding_contract(bundle)


def test_output_is_strict_json_immutable_and_deterministic(bundle):
    before = copy.deepcopy(bundle)
    first = build_open_interest_and_funding_contract(bundle)
    second = build_open_interest_and_funding_contract(copy.deepcopy(bundle))
    json.dumps(first, ensure_ascii=False, allow_nan=False, sort_keys=False)
    assert first == second and bundle == before
    first["context"]["asset"] = "MUTATED"
    assert bundle == before and second["context"]["asset"] == "BTC"
