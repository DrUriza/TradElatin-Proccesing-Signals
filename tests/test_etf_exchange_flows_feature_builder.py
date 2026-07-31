import math

from etf_exchange_flows_processing_helpers import NOW, cloned_input
from processing_signals.processing.etf_exchange_flows.etf_exchange_flows_feature_builder import build_etf_exchange_flows_features


def build(contract=None, **kwargs):
    return build_etf_exchange_flows_features(input_contract=contract or cloned_input(), generated_at=NOW, **kwargs)


def test_etf_latest_period_and_cumulative_use_same_row_prices():
    result = build()
    etf = result["features"]["etf"]
    assert etf["net_flow_usd_latest"]["value"] == -120
    assert etf["net_flow_btc_latest"]["value"] == -2
    assert etf["period_flow_usd"]["7d"]["value"] == -20
    assert etf["period_flow_btc"]["7d"]["value"] == 0
    cumulative = result["series"]["etf_cumulative_flow"]
    assert cumulative[-1]["cumulative_flow_usd"] == -20 and cumulative[-1]["cumulative_flow_btc"] == 0


def test_missing_and_nonpositive_price_are_controlled():
    contract = cloned_input()
    contract["datasets"]["etf_flows_daily"][-1]["price_usd"] = None
    result = build(contract)
    assert result["features"]["etf"]["net_flow_btc_latest"]["reason"] == "price_missing"
    assert result["features"]["etf"]["period_flow_btc"]["7d"]["status"] == "partial"
    contract["datasets"]["etf_flows_daily"][-1]["price_usd"] = 0
    assert build(contract)["features"]["etf"]["net_flow_btc_latest"]["reason"] == "price_not_positive"


def test_funds_signed_share_aum_and_issuer_policy():
    funds = {item["ticker"]: item for item in build()["snapshots"]["funds"]}
    assert funds["GBTC"]["periods"]["1d"]["period_signed_flow_share"]["value"] == -0.3
    assert funds["IBIT"]["periods"]["1d"]["period_signed_flow_share"]["value"] == 0.7
    assert funds["IBIT"]["periods"]["1d"]["period_signed_flow_share"]["share_basis"] == "gross_absolute_flow"
    assert funds["GBTC"]["aum_share"]["value"] == 0.4
    assert funds["GBTC"]["issuer_flow"]["reason"] == "issuer_identity_unavailable"


def test_aum_reconciliation_keeps_reported_and_calculated_separate():
    result = build()["features"]
    assert result["etf"]["reported_total_aum_usd"]["value"] == 1100
    assert result["etf"]["calculated_fund_aum_usd"]["value"] == 1000
    aum = result["provider_reconciliation"]["aum"]
    assert aum["difference_usd"]["value"] == -100
    assert math.isclose(aum["difference_percent"]["value"], -9.090909090909092)


def test_premium_is_preserved_not_recalculated():
    result = build()
    assert result["features"]["premium_discount"]["gbtc_latest"]["value"] == 7.25
    assert result["series"]["fund_premium_discount"][0]["premium_discount_percent"] == 7.25


def test_common_anchor_pressure_and_netflow_reconciliation():
    result = build()
    flows = result["features"]["exchange_flows"]
    pressure = result["features"]["pressure"]["flow_24h"]
    assert flows["inflow_24h"]["value"] == 48 and flows["outflow_24h"]["value"] == 24
    assert flows["netflow_24h_reported"]["value"] == 24 and flows["netflow_24h_calculated"]["value"] == 24
    assert pressure["timestamp"] == NOW and pressure["window_start"] == NOW-86400
    assert math.isclose(pressure["value"], 1/3) and pressure["status"] == "available"


def test_balances_remain_separate_and_spread_is_difference():
    result = build()["features"]
    balances = result["exchange_balances"]
    assert balances["coinglass_total"]["value"] == 300
    assert balances["cryptoquant_reserve"]["value"] == 1000
    assert balances["glassnode_secondary"]["value"] == 990
    spread = result["provider_reconciliation"]["exchange_balance"]
    assert spread["difference"] == 10 and "average" not in spread
