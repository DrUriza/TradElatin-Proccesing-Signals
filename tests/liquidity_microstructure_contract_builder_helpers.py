from liquidity_microstructure_classification_helpers import processing_contract
from processing_signals.classification.liquidity_microstructure import classify_liquidity_microstructure


def bundle():
    processing = processing_contract()
    return {"processing": processing, "classification": classify_liquidity_microstructure(processing)}


def runtime(**changes):
    value = {"data_mode": "synthetic", "is_demo": True, "generated_at": "2025-01-01T00:00:00+00:00",
             "updated_at": "2025-01-01T00:00:00+00:00", "connection_status": "not_reported", "cache_status": "not_reported",
             "latency_ms": None, "refresh_interval_seconds": None, "cache_ttl_seconds": None}
    value.update(changes)
    return value
