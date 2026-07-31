"""Atomic Classification tests for ETF exchange flows."""
import pytest

from etf_exchange_flows_classification_helpers import NOW, PARAMETERS, direction, feature
from processing_signals.classification.etf_exchange_flows import (
    classify_aum_reconciliation_state,
    classify_etf_flow_direction,
    classify_etf_flow_persistence,
    classify_exchange_pressure_regime,
    classify_gbtc_premium_regime,
)


@pytest.mark.parametrize(("value", "state"), [(1, "inflow"), (0, "neutral"), (-1, "outflow")])
def test_direction_sign_only(value, state):
    result = classify_etf_flow_direction(feature(value), range_id="1d", generated_timestamp=NOW, parameters=PARAMETERS)
    assert result["state"] == state and result["status"] == "available"


@pytest.mark.parametrize(("value", "state"), [(-0.25, "strong_exchange_outflow"),
    (-0.249, "exchange_outflow"), (-0.10, "balanced"), (0.10, "balanced"),
    (0.101, "exchange_inflow"), (0.25, "strong_exchange_inflow")])
def test_pressure_exact_boundaries(value, state):
    result = classify_exchange_pressure_regime(feature(value, unit="ratio"), generated_timestamp=NOW, parameters=PARAMETERS)
    assert result["state"] == state


@pytest.mark.parametrize(("value", "state"), [(-0.5, "discount"), (-0.499, "near_par"),
    (0.499, "near_par"), (0.5, "premium")])
def test_gbtc_exact_boundaries(value, state):
    assert classify_gbtc_premium_regime(feature(value, unit="percent"), generated_timestamp=NOW,
        parameters=PARAMETERS)["state"] == state


@pytest.mark.parametrize(("value", "state"), [(2, "aligned"), (-2, "aligned"), (2.001, "watch"),
    (5, "watch"), (-5, "watch"), (5.001, "divergent")])
def test_aum_exact_boundaries(value, state):
    assert classify_aum_reconciliation_state(feature(value, unit="percent"), generated_timestamp=NOW,
        parameters=PARAMETERS)["state"] == state


@pytest.mark.parametrize(("states", "expected"), [
    (("inflow", "inflow", "inflow"), "persistent_inflow"),
    (("outflow", "inflow", "inflow"), "inflow_reversal"),
    (("neutral", "neutral", "inflow"), "inflow_weakening"),
    (("outflow", "outflow", "outflow"), "persistent_outflow"),
    (("inflow", "outflow", "outflow"), "outflow_reversal"),
    (("neutral", "neutral", "outflow"), "outflow_weakening"),
    (("neutral", "neutral", "neutral"), "neutral"),
    (("inflow", "outflow", "neutral"), "mixed"),
])
def test_all_persistence_branches(states, expected):
    directions = {name: direction(state) for name, state in zip(("1d", "7d", "30d"), states)}
    directions["90d"] = direction("outflow")
    assert classify_etf_flow_persistence(directions)["state"] == expected


def test_atomic_partial_wrong_unit_and_future():
    partial = classify_etf_flow_direction(feature(1, status="partial"), range_id="1d",
                                          generated_timestamp=NOW, parameters=PARAMETERS)
    wrong = classify_etf_flow_direction(feature(1, unit="BTC"), range_id="1d",
                                        generated_timestamp=NOW, parameters=PARAMETERS)
    future = classify_etf_flow_direction(feature(1, data_as_of=NOW + 1), range_id="1d",
                                         generated_timestamp=NOW, parameters=PARAMETERS)
    assert (partial["state"], partial["status"]) == ("inflow", "partial")
    assert (wrong["state"], wrong["status"], wrong["reason"]) == (None, "invalid", "invalid_unit")
    assert (future["state"], future["reason"]) == (None, "future_timestamp")
