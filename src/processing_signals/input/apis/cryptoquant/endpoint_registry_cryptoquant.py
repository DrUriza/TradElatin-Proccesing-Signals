"""Endpoint registry adapter for CryptoQuant endpoints."""

from pathlib import Path

from processing_signals.input.apis.registry_helpers import load_json_endpoint_registry


PROVIDER = "cryptoquant"
SYNTHETIC_TIMEFRAMES = ["1m", "5m", "15m", "4h"]
ENDPOINTS = load_json_endpoint_registry(PROVIDER, Path(__file__).with_name("cryptoquant_endpoints.json"))
