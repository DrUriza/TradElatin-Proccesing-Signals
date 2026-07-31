"""Functional contract tests for ETF exchange-flow screen Contract Builder v0.1."""
from copy import deepcopy
import json

import pytest

from etf_exchange_flows_classification_helpers import NOW, cloned_processing
from processing_signals.classification.etf_exchange_flows import (
    EtfExchangeFlowsContractBuilder,
    build_etf_exchange_flows_contract,
    classify_etf_exchange_flows,
    run_etf_exchange_flows_contract_builder,
)


def contracts(*, daily=True):
    processing = cloned_processing()
    if daily:
        processing["series"]["exchange_netflow"]["day"] = deepcopy(
            processing["series"]["exchange_netflow"]["hour"]
        )
    classification = classify_etf_exchange_flows(processing_contract=processing)
    return processing, classification


def build(*, selected_range="30d", daily=True):
    processing, classification = contracts(daily=daily)
    return build_etf_exchange_flows_contract(
        processing_contract=processing,
        classification_contract=classification,
        selected_range=selected_range,
    )


def test_cb01_root_and_public_api():
    processing, classification = contracts()
    output = EtfExchangeFlowsContractBuilder().build(
        processing_contract=processing, classification_contract=classification
    )
    assert output["schema"] == {
        "id": "trad_elatin.etf_exchange_flows.screen.v1",
        "version": "1.0.0",
    }
    assert output["screen"] == {
        "id": "etf_exchange_flows",
        "route": "/etf-exchange-flows",
        "title": "ETF & Exchange Flows",
        "family": "etf_exchange_flows",
    }
    assert output["stage"] == "screen_contract" and output["version"] == "0.1"
    assert run_etf_exchange_flows_contract_builder(
        processing_contract=processing, classification_contract=classification
    ) == output


@pytest.mark.parametrize(
    ("range_id", "seconds", "interval"),
    (("1d", 86_400, "hour"), ("7d", 604_800, "hour"),
     ("30d", 2_592_000, "day"), ("90d", 7_776_000, "day")),
)
def test_cb02_cb05_ranges_and_netflow_interval(range_id, seconds, interval):
    output = build(selected_range=range_id)
    assert output["range_selector"]["selected"] == range_id
    assert output["provenance"]["parameters"]["range_seconds"] == seconds
    assert output["provenance"]["parameters"]["exchange_netflow_source_interval"] == interval
    assert output["charts"]["exchange_net_flow"]["source_path"].endswith(interval)


def test_cb06_kpis_use_exact_processing_sources():
    processing, classification = contracts()
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification, selected_range="7d"
    )
    expected = {
        "etf_net_flow": processing["features"]["etf"]["period_flow_usd"]["7d"]["value"],
        "total_aum": processing["features"]["etf"]["reported_total_aum_usd"]["value"],
        "exchange_inflow": processing["features"]["exchange_flows"]["inflow_24h"]["value"],
        "exchange_outflow": processing["features"]["exchange_flows"]["outflow_24h"]["value"],
        "exchange_balance": processing["features"]["exchange_balances"]["cryptoquant_reserve"]["value"],
        "gbtc_premium": processing["features"]["premium_discount"]["gbtc_latest"]["value"],
        "exchange_flow_pressure": processing["features"]["pressure"]["flow_24h"]["value"],
    }
    assert {name: item["value"] for name, item in output["kpis"].items()} == expected


def test_cb07_aum_reported_is_not_calculated():
    processing, classification = contracts()
    processing["features"]["etf"]["reported_total_aum_usd"]["value"] = 123.0
    processing["features"]["etf"]["calculated_fund_aum_usd"]["value"] = 999.0
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification
    )
    assert output["kpis"]["total_aum"]["value"] == 123.0


def test_cb08_balance_is_cryptoquant_not_other_provider():
    processing, classification = contracts()
    processing["features"]["exchange_balances"]["cryptoquant_reserve"]["value"] = 111.0
    processing["features"]["exchange_balances"]["coinglass_total"]["value"] = 222.0
    processing["features"]["exchange_balances"]["glassnode_secondary"]["value"] = 333.0
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification
    )
    assert output["kpis"]["exchange_balance"]["value"] == 111.0
    assert output["kpis"]["exchange_balance"]["provider"] == "cryptoquant"


def test_cb09_pressure_and_reported_netflow_are_not_recalculated():
    processing, classification = contracts()
    processing["features"]["pressure"]["flow_24h"]["value"] = 0.123
    processing["features"]["exchange_flows"]["netflow_24h_calculated"]["value"] = 999.0
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification, selected_range="1d"
    )
    assert output["kpis"]["exchange_flow_pressure"]["value"] == 0.123
    assert all(point["value"] != 999.0 for point in output["charts"]["exchange_net_flow"]["points"])


def test_cb10_exact_open_closed_range_filter():
    processing, classification = contracts()
    processing["series"]["etf_flow_daily"] = [
        {"timestamp": NOW - 86_400, "flow_usd": 1.0, "provider": "coinglass", "endpoint_id": "a"},
        {"timestamp": NOW - 86_399, "flow_usd": 2.0, "provider": "coinglass", "endpoint_id": "a"},
        {"timestamp": NOW, "flow_usd": 3.0, "provider": "coinglass", "endpoint_id": "a"},
    ]
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification, selected_range="1d"
    )
    assert [point["value"] for point in output["charts"]["etf_flow_daily"]["points"]] == [2.0, 3.0]


def test_cb11_cumulative_is_filtered_without_rebasing():
    processing, classification = contracts()
    processing["series"]["etf_cumulative_flow"] = [
        {"timestamp": NOW - 10, "cumulative_flow_usd": 500.0, "provider": "coinglass", "endpoint_id": "a"},
        {"timestamp": NOW, "cumulative_flow_usd": 450.0, "provider": "coinglass", "endpoint_id": "a"},
    ]
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification, selected_range="1d"
    )
    assert [point["value"] for point in output["charts"]["etf_cumulative_net_flow"]["points"]] == [500.0, 450.0]
    assert output["provenance"]["parameters"]["cumulative_series_rebased"] is False


def test_cb12_exchange_balance_preserves_entities_and_providers():
    output = build(selected_range="1d")
    point = output["charts"]["exchange_balance"]["points"][0]
    assert {key: point[key] for key in ("exchange_name", "symbol", "provider", "endpoint_id")} == {
        "exchange_name": "A", "symbol": "BTC", "provider": "coinglass",
        "endpoint_id": "exchange_balance_chart",
    }


def test_cb13_glassnode_overlay_is_explicitly_unavailable():
    overlay = build()["charts"]["exchange_balance"]["overlays"]["glassnode_balance_secondary"]
    assert overlay == {"status": "unavailable", "reason": "overlay_semantics_not_confirmed", "series": []}


@pytest.mark.parametrize("range_id", ("1d", "7d", "30d", "90d"))
def test_cb14_cb17_fund_table_uses_precomputed_range(range_id):
    processing, classification = contracts()
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification, selected_range=range_id
    )
    rows = output["tables"]["etf_funds"]["rows"]
    assert len(rows) == len(processing["snapshots"]["funds"])
    by_ticker = {row["ticker"]: row for row in rows}
    for source in processing["snapshots"]["funds"]:
        assert by_ticker[source["ticker"]]["flow_usd"]["value"] == source["periods"][range_id]["period_flow_usd"]["value"]
        assert by_ticker[source["ticker"]]["signed_flow_share"]["value"] == source["periods"][range_id]["period_signed_flow_share"]["value"]


def test_cb18_funds_do_not_invent_sosovalue_and_issuer_is_unavailable():
    output = build()
    assert "sosovalue" not in json.dumps(output).lower()
    for row in output["tables"]["etf_funds"]["rows"]:
        assert row["issuer_flow"]["status"] == "unavailable"
        assert row["issuer_flow"]["reason"] == "issuer_identity_unavailable"


def test_cb19_classification_states_are_exact_deep_copies():
    processing, classification = contracts()
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification
    )
    assert output["classification_states"] == classification["classifications"]
    classification["classifications"]["etf_flow_persistence"]["state"] = "mutated"
    assert output["classification_states"]["etf_flow_persistence"]["state"] != "mutated"


def test_cb20_mode_data_mode_demo_are_propagated():
    processing, classification = contracts()
    processing.update(mode="recovery", data_mode="synthetic", is_demo=True)
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification
    )
    assert (output["mode"], output["data_mode"], output["is_demo"]) == ("recovery", "synthetic", True)


def test_cb21_generated_at_does_not_determine_data_as_of():
    processing, classification = contracts()
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification,
        generated_at="2099-01-01T00:00:00Z",
    )
    assert output["context"]["generated_at"] == "2099-01-01T00:00:00Z"
    assert output["quality"]["data_as_of"] <= processing["data_as_of"]


def test_cb22_quality_ok_when_all_required_available():
    output = build(selected_range="30d", daily=True)
    assert output["quality"]["status"] == "ok"
    assert not output["quality"]["partial"] and not output["quality"]["unavailable"]


def test_cb23_missing_required_is_partial_when_others_are_usable():
    output = build(selected_range="30d", daily=False)
    assert output["charts"]["exchange_net_flow"]["status"] == "unavailable"
    assert output["quality"]["status"] == "partial"


def test_cb24_optional_overlay_does_not_degrade_quality():
    output = build()
    assert output["quality"]["status"] == "ok"
    assert output["charts"]["exchange_balance"]["overlays"]["glassnode_balance_secondary"]["status"] == "unavailable"


def test_cb25_global_data_as_of_is_causal_minimum():
    processing, classification = contracts()
    processing["features"]["etf"]["period_flow_usd"]["30d"]["data_as_of"] = NOW - 100
    output = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification
    )
    assert output["quality"]["data_as_of"] == NOW - 100


def test_cb26_provenance_is_compact_and_complete():
    output = build(selected_range="7d")
    provenance = output["provenance"]
    assert set(provenance) == {"source_contracts", "field_sources", "providers", "parameters", "warnings"}
    assert provenance["parameters"]["exchange_flow_kpi_window_seconds"] == 86_400
    assert provenance["providers"]["secondary"] == {"exchange_balance": ["glassnode"]}


def test_cb27_strict_json():
    json.dumps(build(), ensure_ascii=False, allow_nan=False)


def test_cb28_deep_immutability_and_independent_outputs():
    processing, classification = contracts()
    before_processing, before_classification = deepcopy(processing), deepcopy(classification)
    first = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification
    )
    second = build_etf_exchange_flows_contract(
        processing_contract=processing, classification_contract=classification
    )
    first["kpis"]["total_aum"]["value"] = -1
    assert processing == before_processing and classification == before_classification
    assert second["kpis"]["total_aum"]["value"] != -1


def test_cb29_no_runtime_or_pipeline_contract_fields():
    serialized = json.dumps(build()).lower()
    assert "credential" not in serialized and "headers" not in serialized
    assert "runtime_context" not in serialized and "pipeline" not in serialized

