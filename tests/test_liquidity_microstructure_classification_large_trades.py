from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_rules import classify_trade_window


def test_large_trade_states_and_no_observations():
    assert classify_trade_window({"event_count": 0}, source_status="available", source_timestamp=1, coverage_complete=True)["state"] == "no_observations"
    assert classify_trade_window({"event_count": 2, "buy_share_percent": 60, "sell_share_percent": 40}, source_status="available",
                                 source_timestamp=1, coverage_complete=True)["state"] == "buy_dominant"
    assert classify_trade_window({"event_count": 2, "buy_share_percent": 40, "sell_share_percent": 60}, source_status="available",
                                 source_timestamp=1, coverage_complete=False)["provisional"] is True
