"""Endpoint registry adapter for CoinGlass endpoints."""

from pathlib import Path

from processing_signals.input.apis.registry_helpers import InputEndpointRegistry


PROVIDER             = "coinglass"
SYNTHETIC_TIMEFRAMES = ["1m", "5m", "15m", "4h"]
REGISTRY             = InputEndpointRegistry()
ENDPOINTS            = REGISTRY.load_json_endpoint_registry(PROVIDER, Path(__file__).with_name("coinglass_endpoints.json"))
