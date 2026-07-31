import pytest

from etf_exchange_flows_helpers import Fetcher, NOW
from processing_signals.input.etf_exchange_flows.etf_exchange_flows_data_raw_preprocessing import (
    determine_etf_exchange_flows_input_mode, run_etf_exchange_flows_input,
)


def test_mode_priority_and_incomplete_state_detection():
    assert determine_etf_exchange_flows_input_mode() == "bootstrap"
    assert determine_etf_exchange_flows_input_mode(existing_contract={"datasets": {}}) == "bootstrap"
    assert determine_etf_exchange_flows_input_mode(recovery_requests=[{}]) == "recovery"
    assert determine_etf_exchange_flows_input_mode(requested_mode="bootstrap", recovery_requests=[{}]) == "bootstrap"


def test_explicit_recovery_requires_requests():
    with pytest.raises(ValueError, match="recovery_requests_required"):
        determine_etf_exchange_flows_input_mode(requested_mode="recovery")


def test_valid_recovery_runs_only_requested_endpoint():
    fetcher = Fetcher()
    result = run_etf_exchange_flows_input(fetcher=fetcher, requested_mode="recovery", exchange_scope="all_exchange", now=NOW,
        recovery_requests=[{"provider": "cryptoquant", "endpoint_id": "exchange_inflow", "window": "hour", "limit": 10}])
    assert len(fetcher.calls) == 1 and result["mode"] == "recovery"


@pytest.mark.parametrize("now", [True, 0, -1, 1.5, None])
def test_invalid_clock_is_rejected(now):
    with pytest.raises(ValueError):
        run_etf_exchange_flows_input(fetcher=Fetcher(), exchange_scope="all_exchange", now=now)
