from liquidity_microstructure_contract_builder_helpers import bundle, runtime
# ruff: noqa: E702
from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_contract_builder import build_liquidity_microstructure_screen_contract


def test_kpis_copy_signed_upstream_values():
    source = bundle(); depth = source["processing"]["markets"]["perpetual"]["order_depth"]["timeframes"]["1m"]["direct_ranges"][-1]["base_quantity"]
    depth.update({"bid": 195.82, "ask": 244.02, "bid_share_percent": 44.52, "imbalance_percent": -10.96})
    current = source["processing"]["markets"]["perpetual"]["orderbook"]["timeframes"]["1m"]["current"]
    current["spread_bps"] = 7.77; current["market_impact"]["worst_side_impact_bps"] = 8.88
    result = build_liquidity_microstructure_screen_contract(source, runtime_context=runtime())
    kpis = {row["metric_id"]: row for row in result["kpis"]["items"]}
    assert (kpis["bid_depth"]["value"], kpis["ask_depth"]["value"]) == (195.82, 244.02)
    assert kpis["liquidity_imbalance"]["value"] == -10.96 and kpis["liquidity_imbalance"]["display_value"] == "-11.0%"
    assert kpis["spread"]["value"] == 7.77 and kpis["impact_1_btc"]["value"] == 8.88
