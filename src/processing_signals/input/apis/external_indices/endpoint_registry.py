"""Endpoint registry for external volatility indices."""

from processing_signals.input.apis.registry_helpers import endpoint


SYNTHETIC_TIMEFRAMES = ["1m", "5m", "15m", "4h"]


ENDPOINTS = [
    endpoint(
        provider="volmex",
        family="options_volatility",
        subtype="bviv",
        path=None,
        coverage_role="primary",
        live_status="external_provider_required",
        data_type="time_series",
        supports_timeframe=True,
        synthetic_timeframes=SYNTHETIC_TIMEFRAMES,
        default_params={},
        notes="BVIV belongs to Volmex. Use synthetic for now; live requires Volmex or a licensed feed.",
    ),
    endpoint(
        provider="cme_cf_benchmarks",
        family="options_volatility",
        subtype="bvx",
        path=None,
        coverage_role="primary",
        live_status="external_provider_required",
        data_type="time_series",
        supports_timeframe=True,
        synthetic_timeframes=SYNTHETIC_TIMEFRAMES,
        default_params={},
        notes="BVX belongs to CME CF Benchmarks. Use synthetic for now; live requires CME/CF Benchmarks or a licensed feed.",
    ),
]
