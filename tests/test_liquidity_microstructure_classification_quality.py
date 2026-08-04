from liquidity_microstructure_classification_helpers import processing_contract
from processing_signals.classification.liquidity_microstructure import classify_liquidity_microstructure


def test_quality_ok_and_processing_invalid():
    source = processing_contract()
    assert classify_liquidity_microstructure(source)["quality"]["status"] == "ok"
    source["quality"]["status"] = "invalid"
    result = classify_liquidity_microstructure(source)
    assert (result["quality"]["status"], result["quality"]["reason"]) == ("invalid", "processing_quality_invalid")


def test_required_unavailable_makes_quality_partial():
    source = processing_contract()
    source["markets"]["spot"]["large_trades"]["status"] = "unavailable"
    assert classify_liquidity_microstructure(source)["quality"]["status"] == "partial"
