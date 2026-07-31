import json

import pytest

from etf_exchange_flows_helpers import Fetcher, NOW, provider_body
from processing_signals.input.etf_exchange_flows.etf_exchange_flows_data_raw_extract import ENDPOINT_SPECS, extract_etf_exchange_flows_raw
from processing_signals.input.etf_exchange_flows.etf_exchange_flows_data_raw_preprocessing import run_etf_exchange_flows_input


def test_endpoint_specific_synthetic_bodies_are_strict_json():
    for provider, endpoints in ENDPOINT_SPECS.items():
        for endpoint in endpoints:
            params = {"window": "hour"} if provider == "cryptoquant" else {}
            body = provider_body(provider, endpoint, params)
            json.dumps(body, allow_nan=False)


def test_synthetic_metadata_stays_outside_provider_body():
    raw = extract_etf_exchange_flows_raw(fetcher=Fetcher(), mode="bootstrap", exchange_scope="all_exchange",
        data_mode="synthetic", is_demo=True, now=NOW)
    body = raw["raw"]["coinglass"]["bitcoin_etf_flows"]["response"]
    assert raw["family"] == "etf_exchange_flows" and raw["is_demo"] is True
    assert not ({"family", "data_mode", "is_demo"} & set(body))


def test_synthetic_requires_demo():
    with pytest.raises(ValueError, match="invalid_data_mode"):
        extract_etf_exchange_flows_raw(fetcher=Fetcher(), mode="bootstrap", exchange_scope="all_exchange",
            data_mode="synthetic", is_demo=False, now=NOW)


def test_family_name_and_pipeline_boundary():
    output = run_etf_exchange_flows_input(fetcher=Fetcher(), requested_mode="bootstrap", exchange_scope="all_exchange",
        data_mode="synthetic", is_demo=True, now=NOW)
    assert output["family"] == "etf_exchange_flows"
