from copy import deepcopy
import json

import pytest

from processing_signals.input.long_short_liquidations.long_short_liquidations_data_raw_extract import (
    ENDPOINT_MANIFEST,
    build_long_short_liquidations_fetch_plan,
)
from processing_signals.input.long_short_liquidations.long_short_liquidations_data_raw_preprocessing import (
    LongShortLiquidationsInputPreprocessor,
)

REFERENCE = 1_740_000_000


def _request(endpoint_id, response, *, status="ok", error=None, request_id=None):
    return {
        "request_id": request_id or endpoint_id,
        "provider": "coinglass",
        "endpoint_id": endpoint_id,
        "path": ENDPOINT_MANIFEST[("coinglass", endpoint_id)],
        "params": {"symbol": "BTC", "range": "1d"},
        "dimensions": {"exchange": None, "asset": "BTC", "symbol": "BTC"},
        "status": status,
        "response": response,
        "error": error,
        "warnings": [],
    }


def _raw(requests, *, mode="recovery"):
    return {
        "family": "long_short_liquidations",
        "stage": "input_raw",
        "mode": mode,
        "reference_timestamp": REFERENCE,
        "execution_timestamp": REFERENCE + 1,
        "requests": requests,
    }


def _map_request(rows):
    return _request("aggregated_liquidation_map", {"code": "0", "data": {"data": rows}})


def _old_map():
    return {
        "status": "available",
        "reason": None,
        "range": "1d",
        "snapshot_observed_at": REFERENCE - 10,
        "source_data_as_of": None,
        "levels": [{"price_level": 9.0}],
        "provenance": {"provider": "coinglass", "endpoint_id": "aggregated_liquidation_map",
                       "path": ENDPOINT_MANIFEST[("coinglass", "aggregated_liquidation_map")],
                       "params": {}, "request_ids": ["old"],
                       "reference_timestamp": REFERENCE - 20,
                       "execution_timestamp": REFERENCE - 10},
        "warnings": [],
        "errors": [],
    }


def _preprocess(requests, *, mode="recovery", existing=None):
    return LongShortLiquidationsInputPreprocessor(existing_contract=existing).preprocess_raw(
        _raw(requests, mode=mode),
    )


def test_all_invalid_snapshot_without_previous_is_invalid():
    output = _preprocess([_map_request({"1": [[1, 2, None, float("nan")]]})])
    dataset = output["providers"]["coinglass"]["aggregated_map"]
    assert dataset["status"] == "invalid"
    assert dataset["reason"] == "all_records_invalid"
    assert dataset["levels"] == []
    assert dataset["snapshot_observed_at"] is None
    assert output["quality"]["status"] == "invalid"


def test_all_invalid_snapshot_with_previous_preserves_previous():
    previous = _old_map()
    existing = {"providers": {"coinglass": {"aggregated_map": previous}}}
    output = _preprocess([_map_request({"1": [[1, 2, None, float("nan")]]})], existing=existing)
    dataset = output["providers"]["coinglass"]["aggregated_map"]
    assert dataset["status"] == "partial"
    assert dataset["reason"] == "latest_snapshot_invalid"
    assert dataset["levels"] == previous["levels"]
    assert dataset["snapshot_observed_at"] == previous["snapshot_observed_at"]
    assert dataset["provenance"] == previous["provenance"]
    assert dataset["latest_attempt"]["invalid_record_count"] == 1


def test_empty_snapshot_is_unavailable():
    dataset = _preprocess([_map_request({})])["providers"]["coinglass"]["aggregated_map"]
    assert dataset["status"] == "unavailable"
    assert dataset["reason"] == "empty_response"
    assert dataset["snapshot_observed_at"] is None


def test_partially_valid_snapshot_is_partial():
    rows = {"1": [[1, 2, None, float("nan")]], "2": [[2, 3, None, None]]}
    dataset = _preprocess([_map_request(rows)])["providers"]["coinglass"]["aggregated_map"]
    assert dataset["status"] == "partial"
    assert dataset["reason"] == "some_records_invalid"
    assert dataset["snapshot_observed_at"] == REFERENCE + 1
    assert len(dataset["levels"]) == 1


def test_bootstrap_without_aggregated_history_is_invalid_quality():
    output = _preprocess([], mode="bootstrap")
    assert output["quality"]["status"] == "invalid"
    assert "coinglass.aggregated_history" in output["quality"]["missing_required_datasets"]


def _core_bootstrap_requests():
    history = _request("aggregated_liquidation_history", {
        "code": "0", "data": [{"time": REFERENCE * 1000,
                                  "aggregated_long_liquidation_usd": 1,
                                  "aggregated_short_liquidation_usd": 2}],
    })
    snapshot = _request("liquidation_exchange_list", {
        "code": "0", "data": [{"exchange": "Binance", "liquidation_usd": 3,
                                  "long_liquidation_usd": 1, "short_liquidation_usd": 2}],
    })
    return [history, snapshot, _map_request({"1": [[1, 2, None, None]]})]


def test_valid_bootstrap_core_can_have_ok_quality_with_informational_warning():
    output = _preprocess(_core_bootstrap_requests(), mode="bootstrap")
    snapshot = output["providers"]["coinglass"]["exchange_snapshot"]
    assert snapshot["status"] == "available"
    assert "provider_timestamp_not_supplied" in snapshot["warnings"]
    assert output["quality"]["status"] == "ok"


def test_incremental_without_discovery_does_not_require_discovery():
    output = _preprocess(_core_bootstrap_requests(), mode="incremental")
    assert "coinglass.supported_exchange_pairs" not in output["quality"]["required_datasets"]
    assert output["quality"]["status"] == "ok"


def test_incremental_failed_core_request_is_partial_quality():
    failed = _request("aggregated_liquidation_history", None, status="error", error="timeout")
    output = _preprocess([failed], mode="incremental")
    dataset = output["providers"]["coinglass"]["aggregated_history"]
    assert dataset["status"] == "unavailable"
    assert dataset["reason"] == "request_failed"
    assert output["quality"]["status"] == "partial"


def test_recovery_requires_only_declared_target_and_preserves_other_data():
    previous = _old_map()
    existing = {"providers": {"coinglass": {"aggregated_map": previous,
                                               "max_pain": {"status": "available", "marker": "same"}}}}
    before = deepcopy(existing)
    output = _preprocess([_map_request({"1": [[1, 2, None, None]]})], existing=existing)
    assert output["quality"]["required_datasets"] == ["coinglass.aggregated_map"]
    assert output["providers"]["coinglass"]["max_pain"] == before["providers"]["coinglass"]["max_pain"]
    assert existing == before


def test_empty_recovery_is_rejected_by_plan_and_preprocessor():
    with pytest.raises(ValueError, match="recovery_requests_required"):
        build_long_short_liquidations_fetch_plan(
            mode="recovery", reference_timestamp=REFERENCE, recovery_requests=[],
        )
    with pytest.raises(ValueError, match="recovery_requests_required"):
        LongShortLiquidationsInputPreprocessor().preprocess_raw(_raw([]))


@pytest.mark.parametrize(
    ("window", "interval", "seconds"),
    [("day", "1d", 86400), ("hour", "1h", 3600), ("min", "1m", 60)],
)
def test_cryptoquant_publishes_response_window(window, interval, seconds):
    request = {
        "request_id": f"cq:{window}",
        "provider": "cryptoquant",
        "endpoint_id": "cryptoquant_liquidations",
        "path": ENDPOINT_MANIFEST[("cryptoquant", "cryptoquant_liquidations")],
        "params": {"exchange": "all_exchange", "symbol": "all_symbol", "window": window},
        "dimensions": {"exchange": "all_exchange", "asset": "BTC", "symbol": "all_symbol"},
        "status": "ok",
        "response": {"status": {"code": 200}, "result": {"window": window, "data": [{
            "date": "2026-07-28T08:00:00", "long_liquidations": None,
            "short_liquidations": None, "long_liquidations_usd": 1,
            "short_liquidations_usd": 2,
        }]}},
        "error": None,
        "warnings": [],
    }
    dataset = _preprocess([request])["providers"]["cryptoquant"]["aggregate_history"]
    assert dataset["window"] == window
    assert dataset["interval"] == interval
    assert dataset["interval_seconds"] == seconds


def test_request_error_without_previous_has_reason():
    failed = _request("aggregated_liquidation_history", None, status="error", error="timeout")
    dataset = _preprocess([failed])["providers"]["coinglass"]["aggregated_history"]
    assert dataset["status"] == "unavailable"
    assert dataset["reason"] == "request_failed"


def test_every_non_available_generated_dataset_has_reason_and_json_is_strict():
    output = _preprocess([_map_request({"1": [[1, 2, None, float("nan")]]})])

    def visit(value):
        if isinstance(value, dict):
            if value.get("status") in {"partial", "unavailable", "invalid"}:
                assert value.get("reason") is not None
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(output)
    json.dumps(output, ensure_ascii=False, allow_nan=False)


def test_raw_and_existing_contract_are_immutable():
    existing = {"providers": {"coinglass": {"aggregated_map": _old_map()}}}
    raw = _raw([_map_request({"1": [[1, 2, None, None]]})])
    existing_before, raw_before = deepcopy(existing), deepcopy(raw)
    LongShortLiquidationsInputPreprocessor(existing_contract=existing).preprocess_raw(raw)
    assert existing == existing_before
    assert raw == raw_before


def test_audit_cases_14_and_28_are_invalid_and_json_safe():
    output = _preprocess([_map_request({"1": [[1, 2, None, {1: "invalid"}]]})])
    dataset = output["providers"]["coinglass"]["aggregated_map"]
    assert dataset["status"] == "invalid"
    assert dataset["reason"] == "all_records_invalid"
    json.dumps(output, allow_nan=False)
