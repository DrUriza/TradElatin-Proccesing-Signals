import pytest

from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_rules import classify_imbalance, classify_impact, classify_spread


@pytest.mark.parametrize(("value", "state"), [(-20, "ask_dominant"), (-10, "ask_dominant"), (-9.999, "ask_leaning"), (-3, "ask_leaning"),
                                                       (-2.999, "balanced"), (0, "balanced"), (2.999, "balanced"), (3, "bid_leaning"),
                                                       (9.999, "bid_leaning"), (10, "bid_dominant"), (20, "bid_dominant")])
def test_imbalance_boundaries(value, state):
    assert classify_imbalance(value)["state"] == state


@pytest.mark.parametrize(("value", "state"), [(0, "tight"), (2, "tight"), (2.001, "normal"), (5, "normal"),
                                                       (5.001, "wide"), (10, "wide"), (10.001, "stressed")])
def test_spread_boundaries(value, state):
    assert classify_spread(value)["state"] == state


@pytest.mark.parametrize(("value", "state"), [(0, "low"), (3, "low"), (3.001, "moderate"), (10, "moderate"),
                                                       (10.001, "high"), (25, "high"), (25.001, "severe")])
def test_impact_boundaries(value, state):
    assert classify_impact(value, fully_filled=True)["state"] == state


def test_partial_impact_is_indeterminate():
    result = classify_impact(None, fully_filled=False)
    assert (result["status"], result["state"], result["reason_codes"]) == ("partial", "indeterminate", ["incomplete_market_impact_fill"])
