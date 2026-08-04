from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_processor import process_liquidity_microstructure


def test_direct_ranges_and_aligned_derived_bands_remain_distinct():
    result = process_liquidity_microstructure(liquidity_input())
    depth = result["markets"]["spot"]["order_depth"]["timeframes"]["1m"]
    assert {row["range_percent"] for row in depth["direct_ranges"]} == {1, 5, 10}
    one_five = next(row for row in depth["derived_bands"] if row["name"] == "one_to_five")
    assert one_five["bids_usd"] == 100
    assert one_five["bids_quantity"] == 2
    assert depth["direct_ranges"][0]["source_type"] == "provider_aggregated_depth"


def test_non_monotonic_depth_is_invalid_not_clamped():
    source = liquidity_input()
    rows = source["providers"]["coinglass"]["order_depth"]["spot"]["records"]
    next(row for row in rows if row["timeframe"] == "1m" and row["range_percent"] == 5)["bids_usd"] = 1
    result = process_liquidity_microstructure(source)
    assert result["markets"]["spot"]["order_depth"]["timeframes"]["1m"]["status"] == "invalid"
