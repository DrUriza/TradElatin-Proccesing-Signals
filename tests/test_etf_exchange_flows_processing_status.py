from etf_exchange_flows_processing_helpers import NOW, cloned_input
from processing_signals.processing.etf_exchange_flows import process_etf_exchange_flows


def process(contract=None, **kwargs):
    return process_etf_exchange_flows(input_contract=contract or cloned_input(), generated_at=NOW, **kwargs)


def test_every_feature_wrapper_uses_canonical_status_shape():
    output = process()
    feature = output["features"]["etf"]["net_flow_usd_latest"]
    assert set(feature) >= {"value", "status", "reason", "timestamp", "data_as_of", "unit", "provider", "endpoint_id", "coverage", "warnings"}
    assert output["quality"]["status"] == "ok"


def test_required_isolated_degradation_is_partial():
    contract = cloned_input()
    contract["datasets"]["etf_premium_discount_daily"] = []
    output = process(contract)
    assert output["features"]["premium_discount"]["gbtc_latest"]["status"] == "unavailable"
    assert output["quality"]["status"] == "partial" and output["quality"]["required_usable"] == 6


def test_no_required_usable_is_invalid():
    contract = cloned_input()
    for key in list(contract["datasets"]):
        contract["datasets"][key] = {} if isinstance(contract["datasets"][key], dict) else []
    output = process(contract)
    assert output["quality"]["status"] == "invalid" and output["quality"]["required_usable"] == 0


def test_optional_or_secondary_unavailable_does_not_degrade_global():
    contract = cloned_input(glassnode=False)
    contract["datasets"]["etf_flows_daily"][-1]["price_usd"] = None
    output = process(contract)
    assert output["features"]["etf"]["net_flow_btc_latest"]["status"] == "unavailable"
    assert output["features"]["exchange_balances"]["glassnode_secondary"]["status"] == "unavailable"
    assert output["quality"]["status"] == "ok"


def test_short_hourly_coverage_is_partial_and_zero_pressure_unavailable():
    output = process(cloned_input(hourly=5))
    assert output["features"]["exchange_flows"]["inflow_24h"]["status"] == "partial"
    assert output["quality"]["status"] == "partial"
    contract = cloned_input()
    for endpoint, field in (("exchange_inflow", "inflow_total"), ("exchange_outflow", "outflow_total")):
        for row in contract["datasets"][endpoint]["hour"]:
            row[field] = 0.0
    pressure = process(contract)["features"]["pressure"]["flow_24h"]
    assert pressure["status"] == "unavailable" and pressure["reason"] == "zero_total_flow"


def test_scope_mismatch_is_unavailable_not_mixed():
    contract = cloned_input()
    for row in contract["datasets"]["exchange_outflow"]["hour"]:
        row["exchange_scope"] = "coinbase"
    output = process(contract)
    pressure = output["features"]["pressure"]["flow_24h"]
    assert pressure["status"] == "unavailable" and pressure["reason"] == "exchange_scope_mismatch"


def test_input_endpoint_invalid_is_isolated_as_partial_when_history_survives():
    contract = cloned_input()
    contract["quality"]["endpoints"] = {"cryptoquant.exchange_inflow.hour": {"status": "invalid"}}
    output = process(contract)
    assert output["features"]["exchange_flows"]["inflow_24h"]["status"] == "partial"
    assert output["features"]["exchange_flows"]["inflow_24h"]["reason"] == "source_invalid"
    assert output["quality"]["status"] == "partial"
