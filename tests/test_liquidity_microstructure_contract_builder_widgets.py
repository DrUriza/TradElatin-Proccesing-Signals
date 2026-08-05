from liquidity_microstructure_contract_builder_helpers import bundle, runtime
from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_contract_builder import build_liquidity_microstructure_screen_contract


def test_widgets_provider_exchange_and_runtime_badges():
    result = build_liquidity_microstructure_screen_contract(bundle(), runtime_context=runtime(cache_status="stale"))
    assert set(result["widgets"]) == {"observed_liquidity", "large_trade_pressure", "whale_activity_state", "market_context", "spot_perpetual_comparison", "source_status"}
    assert result["context"]["provider"] == {"id": "coinglass", "label": "CoinGlass"} and result["context"]["exchange"] == "Binance"
    assert {row["id"] for row in result["badges"]} == {"DEMO", "DEGRADED", "STALE"}
    assert all(item.get("label") != "Binance" for item in result["widgets"]["source_status"]["items"])
