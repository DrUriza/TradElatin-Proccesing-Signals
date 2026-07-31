"""Composite, Quality and data-as-of tests for ETF Classification."""
import pytest

from etf_exchange_flows_classification_helpers import NOW, cloned_processing
from processing_signals.classification.etf_exchange_flows import classify_etf_exchange_flows


def set_flow(processing, values):
    for name, value in zip(("1d", "7d", "30d"), values):
        processing["features"]["etf"]["period_flow_usd"][name]["value"] = value


@pytest.mark.parametrize(("flows", "pressure", "state"), [
    ((1, 1, 1), -0.2, "accumulation"),
    ((-1, -1, -1), 0.2, "distribution"),
    ((0, 0, 0), 0, "neutral"),
    ((1, 1, 1), 0.2, "mixed"),
])
def test_composite_states(flows, pressure, state):
    processing = cloned_processing()
    set_flow(processing, flows)
    processing["features"]["pressure"]["flow_24h"]["value"] = pressure
    result = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    assert result["classifications"]["composite_capital_flow_regime"]["state"] == state


def test_composite_pillar_unavailable_invalid_and_partial():
    processing = cloned_processing()
    processing["features"]["pressure"]["flow_24h"].update(status="unavailable", value=None)
    unavailable = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    composite = unavailable["classifications"]["composite_capital_flow_regime"]
    assert (composite["state"], composite["status"], composite["reason"]) == (
        None, "unavailable", "insufficient_classification_evidence")
    processing = cloned_processing()
    processing["features"]["pressure"]["flow_24h"]["unit"] = "USD"
    invalid = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    assert invalid["classifications"]["composite_capital_flow_regime"]["status"] == "invalid"
    processing = cloned_processing()
    processing["features"]["pressure"]["flow_24h"]["status"] = "partial"
    partial = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    assert partial["classifications"]["composite_capital_flow_regime"]["status"] == "partial"


def test_netflow_mismatch_warns_but_does_not_change_composite():
    processing = cloned_processing()
    set_flow(processing, (1, 1, 1))
    processing["features"]["pressure"]["flow_24h"]["value"] = -0.2
    processing["features"]["exchange_flows"]["netflow_24h_reported"]["value"] = 1
    result = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    composite = result["classifications"]["composite_capital_flow_regime"]
    assert composite["state"] == "accumulation" and composite["warnings"] == ["netflow_confirmation_mismatch"]


def test_missing_reported_netflow_is_not_replaced_by_calculated():
    processing = cloned_processing()
    processing["features"]["exchange_flows"]["netflow_24h_reported"].update(status="unavailable", value=None)
    processing["features"]["exchange_flows"]["netflow_24h_calculated"]["value"] = 999
    result = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    assert result["classifications"]["exchange_netflow_regime"]["state"] is None


def test_data_as_of_minimum_quality_and_optional_unavailable():
    processing = cloned_processing()
    processing["features"]["etf"]["period_flow_usd"]["1d"]["data_as_of"] = NOW - 10
    processing["features"]["premium_discount"]["gbtc_latest"].update(status="unavailable", value=None)
    result = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    assert result["data_as_of"] == NOW - 10
    assert result["quality"]["status"] == "ok"


def test_processing_global_partial_and_invalid():
    processing = cloned_processing()
    processing["quality"]["status"] = "partial"
    partial = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    assert partial["classifications"]["data_confidence"]["state"] == "medium"
    processing["quality"]["status"] = "invalid"
    invalid = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    assert invalid["quality"]["status"] == "invalid" and invalid["data_as_of"] is None
