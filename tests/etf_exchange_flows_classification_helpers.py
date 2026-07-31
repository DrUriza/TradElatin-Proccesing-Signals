"""Shared fixtures for ETF exchange-flow Classification tests."""
from copy import deepcopy

from etf_exchange_flows_processing_helpers import NOW, cloned_input
from processing_signals.processing.etf_exchange_flows import process_etf_exchange_flows

PARAMETERS = {
    "etf_deadband_usd": 0.0,
    "gbtc_premium_threshold_percent": 0.5,
    "gbtc_discount_threshold_percent": -0.5,
    "pressure_neutral_threshold": 0.10,
    "pressure_strong_threshold": 0.25,
    "netflow_deadband_btc": 0.0,
    "aum_aligned_max_percent": 2.0,
    "aum_watch_max_percent": 5.0,
}


def processing_output():
    return process_etf_exchange_flows(input_contract=cloned_input(), generated_at=NOW)


def feature(value, *, status="available", unit="USD", data_as_of=NOW):
    return {"value": value, "status": status, "reason": None, "data_as_of": data_as_of,
            "unit": unit, "warnings": [], "coverage": {}}


def direction(state, *, status="available", timestamp=NOW):
    return {"state": state, "status": status, "reason": None, "data_as_of": timestamp,
            "evidence": {}, "source_features": [], "parameters": {}, "warnings": []}


def cloned_processing():
    return deepcopy(processing_output())
