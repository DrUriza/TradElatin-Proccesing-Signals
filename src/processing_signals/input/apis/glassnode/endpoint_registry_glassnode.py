"""Endpoint registry adapter for Glassnode endpoints."""

from pathlib import Path

from processing_signals.input.apis.registry_helpers import InputEndpointRegistry


PROVIDER             = "glassnode"
SYNTHETIC_TIMEFRAMES = ["1m", "5m", "15m", "4h"]
REGISTRY             = InputEndpointRegistry()
ENDPOINTS            = REGISTRY.load_json_endpoint_registry(PROVIDER, Path(__file__).with_name("glassnode_endpoints.json"))
