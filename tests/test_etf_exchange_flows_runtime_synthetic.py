"""Directed checks for the offline ETF runtime fetcher."""
import json

import pytest

from processing_signals.input.etf_exchange_flows.etf_exchange_flows_data_raw_extract import ENDPOINT_SPECS
from processing_signals.runtime.etf_exchange_flows import (
    EtfExchangeFlowsSyntheticFetcher,
    build_etf_exchange_flows_synthetic_body,
)


def test_runtime_synthetic_fetcher_covers_every_etf_endpoint_with_strict_json():
    fetcher = EtfExchangeFlowsSyntheticFetcher()
    for provider, endpoints in ENDPOINT_SPECS.items():
        for endpoint_id in endpoints:
            params = {"window": "hour"} if provider == "cryptoquant" else {}
            body = fetcher(provider=provider, endpoint_id=endpoint_id, path="/synthetic", params=params)
            assert body == build_etf_exchange_flows_synthetic_body(
                provider=provider, endpoint_id=endpoint_id, params=params)
            json.dumps(body, ensure_ascii=False, allow_nan=False)
    assert len(fetcher.calls) == 15


def test_runtime_synthetic_fetcher_rejects_unknown_endpoint_and_invalid_request():
    fetcher = EtfExchangeFlowsSyntheticFetcher()
    with pytest.raises(ValueError, match="unknown_synthetic_endpoint"):
        fetcher(provider="coinglass", endpoint_id="unknown", path="/synthetic", params={})
    with pytest.raises(ValueError, match="invalid_synthetic_fetch_request"):
        fetcher(provider="coinglass", endpoint_id="bitcoin_etf_flows", path="/synthetic", params=[])
