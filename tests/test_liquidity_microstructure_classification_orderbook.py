from copy import deepcopy

from liquidity_microstructure_classification_helpers import processing_contract
from processing_signals.classification.liquidity_microstructure import classify_liquidity_microstructure


def test_orderbook_uses_processing_values_without_recalculation():
    source = processing_contract()
    current = source["markets"]["spot"]["orderbook"]["timeframes"]["1m"]["current"]
    current["spread_bps"] = 10.001
    current["bands"]["full_visible_book"]["quote_notional"]["bid_share_percent"] = 99.0
    current["bands"]["full_visible_book"]["quote_notional"]["imbalance_percent"] = -10.0
    original = deepcopy(source)
    result = classify_liquidity_microstructure(source)
    classified = result["markets"]["spot"]["orderbook"]["timeframes"]["1m"]["classification"]
    assert classified["spread_condition"]["state"] == "stressed"
    assert classified["orderbook_balance"]["quote_notional"]["state"] == "ask_dominant"
    assert source == original
