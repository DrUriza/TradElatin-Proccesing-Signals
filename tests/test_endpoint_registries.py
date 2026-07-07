from processing_signals.input.apis.coinglass.endpoint_registry_coinglass import ENDPOINTS as COINGLASS_ENDPOINTS
from processing_signals.input.apis.cryptoquant.endpoint_registry_cryptoquant import ENDPOINTS as CRYPTOQUANT_ENDPOINTS
from processing_signals.input.apis.glassnode.endpoint_registry_glassnode import ENDPOINTS as GLASSNODE_ENDPOINTS
from processing_signals.input.apis.official_registry import (
    FAMILY_SUBTYPES,
    PRIORITY_ORDER,
    SYNTHETIC_TIMEFRAMES,
    TIMEFRAME_DATA_TYPES,
    resolve_endpoints,
    should_call_live,
)


REQUIRED_FIELDS = {
    "provider",
    "family",
    "subtype",
    "endpoint_name",
    "path",
    "method",
    "coverage_role",
    "live_status",
    "synthetic_status",
    "data_type",
    "supports_timeframe",
    "live_supported_timeframes",
    "synthetic_timeframes",
    "extraction_windows",
    "response_shape",
    "synthetic_file_template",
    "notes",
}


def test_each_provider_declares_every_official_family_subtype_pair():
    expected = {(family, subtype) for family, subtypes in FAMILY_SUBTYPES.items() for subtype in subtypes}
    expected_count = len(expected)
    official_families = set(FAMILY_SUBTYPES)

    for endpoints in [COINGLASS_ENDPOINTS, CRYPTOQUANT_ENDPOINTS, GLASSNODE_ENDPOINTS]:
        assert len(endpoints) == expected_count
        observed = {(endpoint["family"], endpoint["subtype"]) for endpoint in endpoints}
        assert observed == expected
        assert {endpoint["family"] for endpoint in endpoints} == official_families
        assert len({endpoint["family"] for endpoint in endpoints}) == 9
        for family, subtypes in FAMILY_SUBTYPES.items():
            observed_subtypes = {endpoint["subtype"] for endpoint in endpoints if endpoint["family"] == family}
            assert observed_subtypes == set(subtypes)
        assert all(REQUIRED_FIELDS <= endpoint.keys() for endpoint in endpoints)


def test_not_available_entries_are_skipped_for_live_and_synthetic():
    not_available = [endpoint for endpoint in CRYPTOQUANT_ENDPOINTS if endpoint["family"] == "prices_ohlcv"]

    assert not_available
    assert all(endpoint["coverage_role"] == "not_available" for endpoint in not_available)
    assert all(endpoint["live_status"] == "not_available" for endpoint in not_available)
    assert all(endpoint["synthetic_status"] == "skip" for endpoint in not_available)
    assert all(endpoint["path"] is None for endpoint in not_available)
    assert all(not should_call_live(endpoint) for endpoint in not_available)


def test_external_provider_required_keeps_external_provider_and_no_live_call():
    endpoints = [
        endpoint
        for endpoint in [*COINGLASS_ENDPOINTS, *GLASSNODE_ENDPOINTS]
        if endpoint["family"] == "options_volatility" and endpoint["subtype"] in {"bviv", "bvx"}
    ]

    assert endpoints
    assert all(endpoint["coverage_role"] == "not_available" for endpoint in endpoints)
    assert all(endpoint["live_status"] == "external_provider_required" for endpoint in endpoints)
    assert all(endpoint["path"] is None for endpoint in endpoints)
    assert {endpoint["external_provider"] for endpoint in endpoints} == {"volmex", "cme_cf_benchmarks"}
    assert all(not should_call_live(endpoint) for endpoint in endpoints)


def test_live_resolution_uses_official_priority_and_requires_real_path():
    endpoints = [
        {
            "provider": "glassnode",
            "family": "prices_ohlcv",
            "subtype": "spot_ohlcv",
            "coverage_role": "secondary",
            "live_status": "supported",
            "synthetic_status": "supported",
            "path": "/real-secondary",
        },
        {
            "provider": "coinglass",
            "family": "prices_ohlcv",
            "subtype": "spot_ohlcv",
            "coverage_role": "primary",
            "live_status": "supported",
            "synthetic_status": "supported",
            "path": "/real-primary",
        },
        {
            "provider": "cryptoquant",
            "family": "prices_ohlcv",
            "subtype": "spot_ohlcv",
            "coverage_role": "not_available",
            "live_status": "not_available",
            "synthetic_status": "skip",
            "path": None,
        },
    ]

    resolved = resolve_endpoints(endpoints)

    assert [endpoint["provider"] for endpoint in resolved] == ["coinglass", "glassnode"]
    assert PRIORITY_ORDER[("primary", "supported")] < PRIORITY_ORDER[("secondary", "supported")]


def test_snapshot_event_and_heatmap_do_not_create_artificial_timeframes():
    endpoints = [
        endpoint
        for endpoint in COINGLASS_ENDPOINTS
        if endpoint["data_type"] in {"snapshot", "event_list", "heatmap"}
    ]

    assert endpoints
    assert all(endpoint["supports_timeframe"] is False for endpoint in endpoints)
    assert all(endpoint["synthetic_timeframes"] == [] for endpoint in endpoints)
    assert all(endpoint["extraction_windows"] in (["latest"], ["24h"]) for endpoint in endpoints)


def test_timeframe_data_types_use_synthetic_timeframes_and_templates():
    endpoints = [
        endpoint
        for endpoint in [*COINGLASS_ENDPOINTS, *CRYPTOQUANT_ENDPOINTS, *GLASSNODE_ENDPOINTS]
        if endpoint["data_type"] in TIMEFRAME_DATA_TYPES and endpoint["synthetic_status"] == "supported"
    ]

    assert endpoints
    assert all(endpoint["synthetic_timeframes"] == SYNTHETIC_TIMEFRAMES for endpoint in endpoints)
    assert all(endpoint["extraction_windows"] == [] for endpoint in endpoints)
    assert all(endpoint["synthetic_file_template"].endswith("/{timeframe}_raw.json") for endpoint in endpoints)


def test_non_timeframe_synthetic_templates_use_extraction_window():
    endpoints = [
        endpoint
        for endpoint in [*COINGLASS_ENDPOINTS, *CRYPTOQUANT_ENDPOINTS, *GLASSNODE_ENDPOINTS]
        if endpoint["data_type"] in {"snapshot", "event_list", "heatmap"}
        and endpoint["synthetic_status"] == "supported"
    ]

    assert endpoints
    assert all(endpoint["synthetic_file_template"].endswith("/{extraction_window}_raw.json") for endpoint in endpoints)
