from liquidity_microstructure_classification_helpers import processing_contract
from processing_signals.classification.liquidity_microstructure import classify_liquidity_microstructure


def test_direct_and_derived_depth_remain_separate_and_classified():
    result = classify_liquidity_microstructure(processing_contract())
    depth = result["markets"]["spot"]["order_depth"]["timeframes"]["1m"]
    assert depth["direct_ranges"] and depth["derived_bands"]
    assert "classification" in depth["direct_ranges"][0]
    assert depth["classification"]["primary_depth_reference"] == "range_10"
