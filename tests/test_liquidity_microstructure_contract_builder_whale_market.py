from liquidity_microstructure_contract_builder_helpers import bundle, runtime
# ruff: noqa: E702
from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_contract_builder import build_liquidity_microstructure_screen_contract


def test_whale_is_perpetual_and_market_history_is_daily():
    source = bundle(); source["processing"]["whale_activity"]["timeframes"]["1m"]["statistics"]["rolling_z_score_20"] = 9.25
    source["processing"]["market_history"]["changes"]["1d"]["change_percent"] = -12.5
    result = build_liquidity_microstructure_screen_contract(source, runtime_context=runtime(), selected_market="spot")
    assert result["charts"]["whale_activity"]["metadata"]["scope"] == "perpetual"
    assert result["charts"]["whale_activity"]["metadata"]["statistics"]["rolling_z_score_20"] == 9.25
    assert result["charts"]["market_history"]["metadata"]["changes"]["1d"]["change_percent"] == -12.5
    assert result["charts"]["market_history"]["selector_behavior"] == "fixed_asset_daily_context"
