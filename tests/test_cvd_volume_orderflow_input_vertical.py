from __future__ import annotations

import copy
import json

import pytest

from processing_signals.input.cvd_volume_orderflow.cvd_volume_orderflow_data_raw_extract import (
    COINGLASS_CVD_MAX_LIMIT, CvdVolumeOrderflowRawExtractor, build_coinglass_aggregated_cvd_params,
    build_coinglass_footprint_params, build_cryptoquant_taker_params, build_cvd_volume_orderflow_fetch_plan,
    build_glassnode_metric_params, required_base_records,
)
from processing_signals.input.cvd_volume_orderflow.cvd_volume_orderflow_data_raw_preprocessing import (
    detect_internal_gaps, merge_paginated_records, normalize_coinglass_cvd_record, normalize_footprint_snapshot,
    run_cvd_volume_orderflow_input, upsert_records_by_timestamp,
)

REFERENCE = 2_000_000_000


def cvd_row(timestamp: int, *, buy: float = 10.0, sell: float = 8.0, cvd: float = 2.0) -> dict[str, float | int]:
    return {"time": timestamp * 1000, "agg_taker_buy_vol": buy, "agg_taker_sell_vol": sell, "cum_vol_delta": cvd}


def response_for(provider: str, endpoint_id: str, params: dict) -> object:
    if provider == "coinglass" and "aggregated_cvd" in endpoint_id:
        interval = 60 if params["interval"] == "1m" else 900
        end = params.get("end_time", REFERENCE * 1000) // 1000
        count = params["limit"]
        return {"code": "0", "data": [cvd_row(end - offset * interval) for offset in range(count)]}
    if provider == "coinglass":
        return {"code": "0", "data": [[REFERENCE, [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]]]]}
    if provider == "cryptoquant":
        return {"status": {"code": 200, "message": "success"}, "result": {"window": "hour", "data": [{
            "date": "2033-05-18T03:33:20Z", "taker_buy_volume": 10, "taker_sell_volume": 9,
            "taker_buy_ratio": .52, "taker_sell_ratio": .48, "taker_buy_sell_ratio": 1.1}]}}
    return [{"t": REFERENCE, "v": 7}]


def fetcher(*, provider: str, endpoint_id: str, path: str, params: dict) -> object:
    del path
    return response_for(provider, endpoint_id, params)


def small_input(**overrides):
    options = {"fetcher": fetcher, "reference_timestamp": REFERENCE, "clock": lambda: REFERENCE,
        "target_display_records": 1, "warmup_records": 0, "include_footprint": False,
        "include_cryptoquant_confirmation": False, "include_glassnode_confirmation": False}
    options.update(overrides)
    return run_cvd_volume_orderflow_input(**options)


def test_fetch_plan_contains_four_primary_requests_for_bootstrap_and_incremental():
    for mode in ("bootstrap", "incremental"):
        plan = build_cvd_volume_orderflow_fetch_plan(mode=mode, reference_timestamp=REFERENCE, include_footprint=False,
            include_cryptoquant_confirmation=False, include_glassnode_confirmation=False)
        assert [(item["market"], item["timeframe"]) for item in plan] == [
            ("spot", "1m"), ("spot", "15m"), ("futures", "1m"), ("futures", "15m")]
        assert [item["logical_request_id"] for item in plan] == [
            "coinglass:spot:aggregated_cvd:1m", "coinglass:spot:aggregated_cvd:15m",
            "coinglass:futures:aggregated_cvd:1m", "coinglass:futures:aggregated_cvd:15m"]


def test_required_history_and_provider_params_are_frozen():
    assert required_base_records("1m") == 1260
    assert required_base_records("15m") == 24192
    assert build_coinglass_aggregated_cvd_params(exchanges=("Binance", "OKX", "Bybit"), symbol="BTC", timeframe="1m", limit=4500) == {
        "exchange_list": "Binance,OKX,Bybit", "symbol": "BTC", "interval": "1m", "limit": 4500, "unit": "usd"}
    assert build_coinglass_footprint_params(exchange="Binance", symbol="BTCUSDT")["symbol"] == "BTCUSDT"
    assert build_cryptoquant_taker_params(window="hour", limit=5, start_timestamp=0, end_timestamp=1)["from"] == "19700101T000000"
    assert build_glassnode_metric_params(start_timestamp=1, end_timestamp=2) == {
        "a": "BTC", "i": "1h", "c": "USD", "f": "json", "timestamp_format": "unix", "s": 1, "u": 2}


def test_raw_deep_copies_response_and_uses_one_deterministic_clock_value():
    source = {"code": "0", "data": [cvd_row(REFERENCE)]}

    def mutable_fetcher(**kwargs):
        del kwargs
        return source

    raw = CvdVolumeOrderflowRawExtractor(mutable_fetcher, clock=lambda: REFERENCE).run(mode="bootstrap", reference_timestamp=REFERENCE,
        target_display_records=1, warmup_records=0, include_footprint=False, include_cryptoquant_confirmation=False,
        include_glassnode_confirmation=False)
    source["data"][0]["cum_vol_delta"] = 999
    assert raw["requests"][0]["response"]["data"][0]["cum_vol_delta"] == 2
    assert raw["context"]["execution_timestamp"] == REFERENCE
    assert {item["requested_at"] for item in raw["requests"]} == {raw["context"]["requested_at"]}


def test_bootstrap_paginates_15m_beyond_4500_and_collects_24192():
    raw = CvdVolumeOrderflowRawExtractor(fetcher, clock=lambda: REFERENCE).run(mode="bootstrap", reference_timestamp=REFERENCE,
        include_footprint=False, include_cryptoquant_confirmation=False, include_glassnode_confirmation=False)
    pages = [item for item in raw["requests"] if item["logical_request_id"] == "coinglass:spot:aggregated_cvd:15m"]
    merged, metadata, invalid = merge_paginated_records(pages)
    assert len(pages) == 6
    assert len(merged) >= 24192
    assert metadata["pages_succeeded"] == 6
    assert invalid == []
    assert pages[0]["request_id"] == "coinglass:spot:aggregated_cvd:15m:page:0001"
    assert all(page["params"]["limit"] <= COINGLASS_CVD_MAX_LIMIT for page in pages)


@pytest.mark.parametrize(("mode", "expected"), [("empty", "empty_page"), ("repeat", "repeated_page_signature")])
def test_pagination_stops_safely(mode, expected):
    calls = 0

    def special_fetcher(**kwargs):
        nonlocal calls
        calls += 1
        if mode == "empty" and calls == 2:
            return {"code": "0", "data": []}
        end = REFERENCE if mode == "repeat" else kwargs["params"]["end_time"] // 1000
        return {"code": "0", "data": [cvd_row(end - index * 900) for index in range(4500)]}

    request = build_cvd_volume_orderflow_fetch_plan(mode="bootstrap", reference_timestamp=REFERENCE, include_footprint=False,
        include_cryptoquant_confirmation=False, include_glassnode_confirmation=False)[1]
    pages, stop = CvdVolumeOrderflowRawExtractor(special_fetcher, clock=lambda: REFERENCE).execute_paginated_request(request)
    assert stop == expected
    assert len(pages) >= 2


def test_page_error_is_isolated_and_valid_pages_are_preserved():
    pages = [{"page_index": 1, "status": "ok", "response": {"code": "0", "data": [cvd_row(1_700_000_000)]}},
        {"page_index": 2, "status": "error", "response": None, "error": "boom"}]
    records, metadata, invalid = merge_paginated_records(pages)
    assert records == [{"timestamp": 1_700_000_000, "taker_buy_volume_usd": 10.0, "taker_sell_volume_usd": 8.0, "provider_cvd_usd": 2.0}]
    assert metadata["pages_failed"] == 1
    assert invalid[0]["reason"] == "boom"


def test_normalization_timestamps_numeric_validation_and_negative_provider_cvd():
    assert normalize_coinglass_cvd_record(cvd_row(1, cvd=-2))["provider_cvd_usd"] == -2.0
    assert normalize_coinglass_cvd_record({**cvd_row(1), "time": 1_700_000_000})["timestamp"] == 1_700_000_000
    assert normalize_coinglass_cvd_record({**cvd_row(1), "time": 1_700_000_000_000})["timestamp"] == 1_700_000_000
    for value in (float("nan"), float("inf"), True, -1):
        with pytest.raises(ValueError):
            normalize_coinglass_cvd_record({**cvd_row(1), "agg_taker_buy_vol": value})


def test_footprint_requires_ten_positions_and_does_not_calculate_math():
    snapshot = normalize_footprint_snapshot([1, [[1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [1, 2]]])
    assert len(snapshot["levels"]) == 1
    assert snapshot["invalid_levels"][0]["reason"] == "footprint_level_must_have_ten_positions"
    assert not ({"delta", "ratio", "vwap", "imbalance"} & snapshot["levels"][0].keys())


def test_upsert_replaces_timestamp_preserves_history_and_does_not_mutate():
    existing, incoming = [{"timestamp": 1, "value": 1}, {"timestamp": 2, "value": 2}], [{"timestamp": 2, "value": 9}, {"timestamp": 3, "value": 3}]
    before = copy.deepcopy((existing, incoming))
    records, metadata = upsert_records_by_timestamp(existing, incoming)
    assert records == [{"timestamp": 1, "value": 1}, {"timestamp": 2, "value": 9}, {"timestamp": 3, "value": 3}]
    assert metadata["timestamps_replaced"] == [2]
    assert (existing, incoming) == before


def test_gap_detection_does_not_fill_records():
    records = [{"timestamp": 60}, {"timestamp": 180}]
    assert detect_internal_gaps(records, 60)[0]["missing_records"] == 1
    assert len(records) == 2


def test_bootstrap_shape_readiness_quality_and_no_downstream_fields():
    result = small_input()
    assert result["mode"] == "bootstrap"
    assert set(result["markets"]) == {"spot", "futures"}
    assert "general" not in result["markets"]
    assert set(result["readiness"]["target_timeframes"]) == {"1m", "5m", "15m", "1h", "4h", "1d"}
    assert result["readiness"]["target_timeframes"]["5m"]["source_timeframe"] == "1m"
    assert result["readiness"]["target_timeframes"]["1d"]["source_timeframe"] == "15m"
    encoded = json.dumps(result, allow_nan=False)
    for forbidden in ("delta_usd", '"cvd_usd"', "buy_sell_ratio", "vwap", "imbalance", "flow_efficiency", "candlestick"):
        assert forbidden not in encoded


def test_incremental_replaces_timestamp_and_preserves_older_history():
    existing = small_input()
    stamp = existing["markets"]["spot"]["cvd"]["timeframes"]["1m"]["records"][-1]["timestamp"]

    def replacement_fetcher(*, provider, endpoint_id, path, params):
        response = response_for(provider, endpoint_id, params)
        if provider == "coinglass" and endpoint_id == "spot_aggregated_cvd":
            response["data"].append(cvd_row(stamp, buy=99))
        return response

    result = small_input(fetcher=replacement_fetcher, existing_input=existing)
    records = result["markets"]["spot"]["cvd"]["timeframes"]["1m"]["records"]
    assert result["mode"] == "incremental"
    assert next(row for row in records if row["timestamp"] == stamp)["taker_buy_volume_usd"] == 99
    old_first = existing["markets"]["spot"]["cvd"]["timeframes"]["1m"]["records"][0]
    assert next(row for row in records if row["timestamp"] == old_first["timestamp"]) == old_first


def test_recovery_runs_only_explicit_request():
    calls = []

    def recording_fetcher(**kwargs):
        calls.append(copy.deepcopy(kwargs))
        return response_for(kwargs["provider"], kwargs["endpoint_id"], kwargs["params"])

    result = small_input(fetcher=recording_fetcher, requested_mode="recovery", recovery_requests=[{
        "market": "spot", "timeframe": "1m", "start_timestamp": REFERENCE - 120, "end_timestamp": REFERENCE, "records_required": 3}])
    assert result["mode"] == "recovery"
    assert len(calls) == 1
    assert calls[0]["endpoint_id"] == "spot_aggregated_cvd"


def test_optional_sources_remain_separate_and_disabled_has_reason():
    result = small_input(include_footprint=True, include_cryptoquant_confirmation=True, include_glassnode_confirmation=True)
    assert result["markets"]["futures"]["confirmations"]["cryptoquant"]["records"][0]["provider_window"] == "hour"
    assert set(result["markets"]["spot"]["confirmations"]["glassnode"]) == {
        "spot_cvd_sum", "spot_vd_sum", "spot_buying_volume_sum", "spot_selling_volume_sum"}
    disabled = small_input()
    assert disabled["markets"]["spot"]["footprint"]["reason"] == "endpoint_disabled"
    assert disabled["quality"]["status"] == "ok"


def test_same_inputs_and_clock_are_deterministic_and_arguments_immutable():
    exchanges = ["Binance", "OKX", "Bybit"]
    recovery = [{"market": "spot", "timeframe": "1m", "start_timestamp": REFERENCE - 60, "end_timestamp": REFERENCE}]
    before = copy.deepcopy((exchanges, recovery))
    first = small_input(exchanges=exchanges, requested_mode="recovery", recovery_requests=recovery)
    second = small_input(exchanges=exchanges, requested_mode="recovery", recovery_requests=recovery)
    assert first == second
    assert (exchanges, recovery) == before


def test_synthetic_requires_demo_mode():
    with pytest.raises(ValueError, match="data_mode"):
        small_input(is_demo=False)
