from liquidity_microstructure_contract_builder_helpers import bundle, runtime
# ruff: noqa: E702
from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_contract_builder import build_liquidity_microstructure_screen_contract


def test_large_trades_copy_windows_and_threshold_events():
    source = bundle(); trades = source["processing"]["markets"]["perpetual"]["large_trades"]
    trades["windows"]["1m"]["total_volume_usd"] = 123456.0
    trades["large_trade_events"].append({**trades["large_trade_events"][0], "event_id": "small", "meets_configured_threshold": False})
    result = build_liquidity_microstructure_screen_contract(source, runtime_context=runtime())
    assert result["charts"]["large_trades_flow"]["items"][0]["total_volume_usd"] == 123456.0
    assert [row["event_id"] for row in result["tables"]["large_trades"]["rows"]] == ["perpetual-1"]
    assert result["charts"]["large_trades_flow"]["metadata"]["window_semantics"] == "overlapping_lookback_windows"
