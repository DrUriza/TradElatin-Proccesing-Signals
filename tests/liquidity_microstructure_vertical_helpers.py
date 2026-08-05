from liquidity_microstructure_helpers import valid_fetcher


REFERENCE = 1_700_000_000


def runtime():
    return {"data_mode": "synthetic", "is_demo": True, "generated_at": "2023-11-14T22:13:20+00:00",
            "updated_at": "2023-11-14T22:13:20+00:00", "connection_status": "not_reported", "cache_status": "not_reported",
            "latency_ms": None, "refresh_interval_seconds": None, "cache_ttl_seconds": None}


def arguments(**extra):
    value = {"fetcher": valid_fetcher, "runtime_context": runtime(), "input_arguments": {"reference_timestamp": REFERENCE,
             "execution_timestamp": REFERENCE}, "processing_arguments": {"now_timestamp": REFERENCE},
             "classification_arguments": {"now_timestamp": REFERENCE}}
    value.update(extra)
    return value
