import pytest

from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_rules import classify_comparison


@pytest.mark.parametrize(("value", "state"), [(.8, "spot_deeper"), (.801, "comparable_depth"), (1.249, "comparable_depth"), (1.25, "perpetual_deeper")])
def test_depth_ratio_boundaries(value, state):
    assert classify_comparison(value, kind="depth_quote", source_timestamp=1)["state"] == state


@pytest.mark.parametrize(("kind", "value", "state"), [("spread", -1, "perpetual_tighter"), ("spread", 1, "spot_tighter"),
                                                                ("buy_impact", -2, "perpetual_lower_buy_impact"),
                                                                ("sell_impact", 2, "spot_lower_sell_impact")])
def test_difference_boundaries(kind, value, state):
    assert classify_comparison(value, kind=kind, source_timestamp=1)["state"] == state
