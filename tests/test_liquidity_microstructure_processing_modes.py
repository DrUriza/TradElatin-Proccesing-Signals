from copy import deepcopy

from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_feature_builder import build_liquidity_microstructure_features
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_processor import process_liquidity_microstructure


def test_modes_are_deterministic_and_inputs_immutable():
    source = liquidity_input(mode="incremental")
    original = deepcopy(source)
    first = process_liquidity_microstructure(source, now_timestamp=123)
    second = process_liquidity_microstructure(source, now_timestamp=123)
    assert first == second and source == original
    assert first["mode"] == "incremental"


def test_feature_builder_deepcopies_without_recalculation():
    result = process_liquidity_microstructure(liquidity_input())
    features = build_liquidity_microstructure_features(markets=result["markets"], whale_activity=result["whale_activity"],
                                                       market_history=result["market_history"], comparison=result["comparison"])
    features["market_history"]["status"] = "changed"
    assert result["market_history"]["status"] == "available"


def test_previous_processing_is_preserved_only_for_compatible_unavailable_source():
    initial_input = liquidity_input()
    previous = process_liquidity_microstructure(initial_input, now_timestamp=100)
    incremental = liquidity_input(mode="incremental")
    dataset = incremental["providers"]["coinglass"]["orderbook"]["perpetual"]
    dataset["status"], dataset["reason"] = "partial", "update_failed"
    dataset["records"] = [record for record in dataset["records"] if record["timeframe"] != "5m"]
    result = process_liquidity_microstructure(incremental, existing_processing=previous, now_timestamp=101)
    perpetual = result["markets"]["perpetual"]["orderbook"]["timeframes"]
    assert perpetual["5m"]["preserved_from_previous"] is True
    assert perpetual["5m"]["preserved_feature_path"] == "markets.perpetual.orderbook.timeframes.5m"
    assert all("preserved_from_previous" not in perpetual[timeframe] for timeframe in ("1m", "15m", "1h"))
    assert all("preserved_from_previous" not in node for node in result["markets"]["spot"]["orderbook"]["timeframes"].values())
    changed = process_liquidity_microstructure(incremental, existing_processing=previous, now_timestamp=101,
                                               config={"market_impact_quantity_base": 2.0})
    assert "preserved_from_previous" not in changed["markets"]["perpetual"]["orderbook"]["timeframes"]["5m"]


def test_depth_preservation_is_range_granular_and_comparison_is_recalculated():
    initial = liquidity_input()
    previous = process_liquidity_microstructure(initial, now_timestamp=100)
    previous["comparison"] = {"sentinel": "must_not_be_copied"}
    current = liquidity_input(mode="incremental")
    dataset = current["providers"]["coinglass"]["order_depth"]["spot"]
    dataset["status"], dataset["reason"] = "partial", "range_update_failed"
    dataset["records"] = [row for row in dataset["records"] if not (row["timeframe"] == "15m" and row["range_percent"] == 1)]
    original_input, original_previous = deepcopy(current), deepcopy(previous)
    result = process_liquidity_microstructure(current, existing_processing=previous, now_timestamp=101)
    node = result["markets"]["spot"]["order_depth"]["timeframes"]["15m"]
    range_one = [row for row in node["direct_ranges"] if row["range_percent"] == 1]
    assert range_one and all(row["preserved_from_previous"] for row in range_one)
    assert all("preserved_from_previous" not in row for row in node["direct_ranges"] if row["range_percent"] in {5, 10})
    assert any(band["name"] == "one_to_five" for band in node["derived_bands"])
    assert "sentinel" not in result["comparison"]
    assert current == original_input and previous == original_previous
    changed_ranges = process_liquidity_microstructure(current, existing_processing=previous, now_timestamp=101,
                                                      config={"depth_ranges_percent": (5, 10)})
    changed_node = changed_ranges["markets"]["spot"]["order_depth"]["timeframes"]["15m"]
    assert not any(row.get("preserved_from_previous") for row in changed_node["direct_ranges"])


def test_invalid_source_identity_is_never_preserved():
    initial = liquidity_input()
    previous = process_liquidity_microstructure(initial, now_timestamp=100)
    current = liquidity_input(mode="incremental")
    dataset = current["providers"]["coinglass"]["orderbook"]["perpetual"]
    dataset["status"], dataset["reason"] = "invalid", "provider_invalid"
    dataset["records"][1]["bid_levels"][0]["price"] = 200
    result = process_liquidity_microstructure(current, existing_processing=previous, now_timestamp=101)
    node = result["markets"]["perpetual"]["orderbook"]["timeframes"]["5m"]
    assert node["status"] == "invalid"
    assert "preserved_from_previous" not in node
