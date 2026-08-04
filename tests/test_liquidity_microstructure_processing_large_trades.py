from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_processor import process_liquidity_microstructure


def test_trade_filter_quantity_windows_and_unknown_coverage():
    source = liquidity_input()
    events = source["providers"]["coinglass"]["large_trades"]["spot"]["events"]
    events.append({**events[0], "event_id": "small", "timestamp": source["reference_timestamp"] - 60,
                   "side": "sell", "volume_usd": 9_000.0, "meets_configured_threshold": False})
    events.sort(key=lambda event: event["timestamp"])
    result = process_liquidity_microstructure(source)
    trades = result["markets"]["spot"]["large_trades"]
    assert len(trades["observed_events"]) == 2 and len(trades["large_trade_events"]) == 1
    assert next(event for event in trades["observed_events"] if event["event_id"] == "spot-1")["quantity_base"] == 200
    assert trades["windows"]["1m"]["event_count"] == 1
    assert trades["coverage"]["coverage_complete"] is False
