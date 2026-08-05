import pytest

from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_rules import classify_market_change, classify_whale


@pytest.mark.parametrize(("value", "state"), [(-3, "extreme_negative_deviation"), (-2, "extreme_negative_deviation"),
                                                       (-1.999, "elevated_negative_deviation"), (-1, "elevated_negative_deviation"),
                                                       (-.999, "normal_range"), (0, "normal_range"), (.999, "normal_range"),
                                                       (1, "elevated_positive_deviation"),
                                                       (1.999, "elevated_positive_deviation"), (2, "extreme_positive_deviation"),
                                                       (3, "extreme_positive_deviation")])
def test_whale_boundaries(value, state):
    assert classify_whale(value, source_status="available", source_timestamp=1)["state"] == state


@pytest.mark.parametrize(("value", "state"), [(-.25, "falling"), (-.249, "flat"), (0, "flat"), (.249, "flat"), (.25, "rising"), (.251, "rising")])
def test_market_history_boundaries(value, state):
    assert classify_market_change(value, source_status="available", source_timestamp=1)["state"] == state
