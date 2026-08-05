from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_processor import process_liquidity_microstructure


def test_markets_timeframes_current_and_real_level_impact():
    result = process_liquidity_microstructure(liquidity_input(), now_timestamp=1_700_000_001)
    assert set(result["markets"]) == {"spot", "perpetual"}
    current = result["markets"]["spot"]["orderbook"]["timeframes"]["1m"]["current"]
    assert current["best_bid"] == 99
    assert current["best_ask"] == 101
    assert current["mid_price"] == 100
    assert current["market_impact"]["buy"]["levels_consumed"] == 2


def test_crossed_and_unverified_books_are_not_repaired_or_guessed():
    source = liquidity_input()
    record = source["providers"]["coinglass"]["orderbook"]["spot"]["records"][0]
    record["bid_levels"][0]["price"] = 101
    result = process_liquidity_microstructure(source)
    assert result["markets"]["spot"]["orderbook"]["timeframes"]["1m"]["history"][0]["reason"] == "crossed_or_locked_order_book"
    record.pop("bid_levels")
    record.pop("ask_levels")
    record["provider_side_0"], record["provider_side_1"] = [], []
    result = process_liquidity_microstructure(source)
    assert result["markets"]["spot"]["orderbook"]["timeframes"]["1m"]["history"][0]["reason"] == "orderbook_side_mapping_unverified"
