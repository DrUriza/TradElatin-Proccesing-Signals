from __future__ import annotations

import copy
import json
import math

import pytest

from processing_signals.input.volatility_market_regimes.volatility_market_regimes_data_raw_extract import (
    COINGLASS_MAX_LIMIT, DERIBIT_MAX_PAGES, ENDPOINT_MANIFEST, ENDPOINT_NORMALIZATION,
    VolatilityMarketRegimesRawExtractor, build_coinglass_positioning_params,
    build_deribit_volatility_index_params, build_glassnode_realized_volatility_params,
    build_volatility_market_regimes_fetch_plan, extract_volatility_market_regimes_raw,
)
from processing_signals.input.volatility_market_regimes.volatility_market_regimes_data_raw_preprocessing import (
    detect_hourly_gaps, determine_volatility_market_regimes_input_mode, normalize_coinglass_positioning_record,
    normalize_deribit_volatility_index_record, normalize_glassnode_realized_volatility_record,
    preprocess_volatility_market_regimes_input, unwrap_coinglass_positioning_response,
    unwrap_deribit_volatility_index_response, unwrap_glassnode_realized_volatility_response,
    upsert_timestamp_records,
)

NOW = 1_741_618_800


def coinglass(timestamp=NOW, **changes):
    row = {"time": timestamp * 1000, "top_position_long_percent": 52.15,
        "top_position_short_percent": 47.85, "top_position_long_short_ratio": 1.09}
    row.update(changes)
    return {"code": "0", "msg": "success", "data": [row]}


def glassnode(timestamp=NOW, value=.334):
    return [{"t": timestamp, "v": value}]


def deribit(timestamp=NOW, continuation=None, candle=None):
    return {"jsonrpc": "2.0", "id": 1, "result": {
        "data": [candle or [timestamp * 1000, .481, .492, .478, .489]], "continuation": continuation}}


def fetcher(*, provider, endpoint_id, path, params):
    del endpoint_id, path
    if provider == "coinglass":
        return coinglass(params["end_time"] // 1000)
    if provider == "glassnode":
        return glassnode(params["u"])
    return deribit(params["params"]["end_timestamp"] // 1000)


def raw(mode="bootstrap", **kwargs):
    if mode == "bootstrap":
        kwargs.setdefault("bootstrap_history_days", 1)
    return extract_volatility_market_regimes_raw(fetcher=kwargs.pop("fetcher", fetcher), mode=mode,
        reference_timestamp=kwargs.pop("reference_timestamp", NOW), clock=kwargs.pop("clock", lambda: NOW + 5), **kwargs)


def test_exact_local_manifest_and_normalization_metadata():
    assert ENDPOINT_MANIFEST == {
        ("coinglass", "top_position_long_short_ratio"): "/api/futures/top-long-short-position-ratio/history",
        ("glassnode", "realized_volatility"): "/v1/metrics/market/realized_volatility_1_week",
        ("deribit", "volatility_index"): "/api/v2/public/get_volatility_index_data"}
    assert ENDPOINT_NORMALIZATION[("coinglass", "top_position_long_short_ratio")]["value_scale"] == "provider_percent"
    assert ENDPOINT_NORMALIZATION[("glassnode", "realized_volatility")]["value_scale"] == "fraction_to_percent"
    assert ENDPOINT_NORMALIZATION[("deribit", "volatility_index")]["timestamp_unit"] == "milliseconds"


def test_parameter_builders_use_frozen_dimensions_and_units():
    cg = build_coinglass_positioning_params(start_timestamp=1, end_timestamp=3601, limit=2)
    assert cg == {"exchange": "Binance", "symbol": "BTCUSDT", "interval": "1h", "limit": 2,
        "start_time": 1000, "end_time": 3_601_000}
    assert build_glassnode_realized_volatility_params(start_timestamp=1, end_timestamp=2) == {
        "a": "BTC", "s": 1, "u": 2, "i": "1h", "f": "json", "timestamp_format": "unix"}
    assert build_deribit_volatility_index_params(start_timestamp=1, end_timestamp=2) == {"jsonrpc": "2.0", "id": 1,
        "method": "public/get_volatility_index_data", "params": {"currency": "BTC", "start_timestamp": 1000,
            "end_timestamp": 2000, "resolution": "3600"}}


def test_bootstrap_plan_three_providers_120_days_chunks_and_overlap():
    plan = build_volatility_market_regimes_fetch_plan(mode="bootstrap", reference_timestamp=NOW)
    assert {item["provider"] for item in plan} == {"coinglass", "glassnode", "deribit"}
    cg = [item for item in plan if item["provider"] == "coinglass"]
    assert len(cg) == 3 and all(item["params"]["limit"] <= COINGLASS_MAX_LIMIT for item in cg)
    assert cg[0]["params"]["start_time"] == (NOW - 120 * 86400) * 1000
    assert cg[0]["params"]["end_time"] == cg[1]["params"]["start_time"]
    gn = next(item for item in plan if item["provider"] == "glassnode")
    db = next(item for item in plan if item["provider"] == "deribit")
    assert (gn["params"]["s"], gn["params"]["u"]) == (NOW - 120 * 86400, NOW)
    assert db["params"]["params"]["resolution"] == "3600"
    assert plan == build_volatility_market_regimes_fetch_plan(mode="bootstrap", reference_timestamp=NOW)


def test_incremental_exact_12_hour_window_one_request_each():
    plan = build_volatility_market_regimes_fetch_plan(mode="incremental", reference_timestamp=NOW)
    assert len(plan) == 3
    for item in plan:
        params = item["params"]["params"] if item["provider"] == "deribit" else item["params"]
        divisor = 1000 if item["provider"] in {"coinglass", "deribit"} else 1
        start = params["start_timestamp"] if item["provider"] == "deribit" else params.get("start_time", params.get("s"))
        end = params["end_timestamp"] if item["provider"] == "deribit" else params.get("end_time", params.get("u"))
        assert end // divisor - start // divisor == 12 * 3600


def test_recovery_requires_targets_validates_scope_and_adds_padding():
    with pytest.raises(ValueError, match="required"):
        build_volatility_market_regimes_fetch_plan(mode="recovery", reference_timestamp=NOW, recovery_requests=[])
    with pytest.raises(ValueError, match="unknown"):
        build_volatility_market_regimes_fetch_plan(mode="recovery", reference_timestamp=NOW,
            recovery_requests=[{"provider": "x", "endpoint_id": "x", "start_timestamp": 1, "end_timestamp": 2}])
    target = {"provider": "glassnode", "endpoint_id": "realized_volatility", "start_timestamp": NOW - 7200, "end_timestamp": NOW - 3600}
    plan = build_volatility_market_regimes_fetch_plan(mode="recovery", reference_timestamp=NOW, recovery_requests=[target])
    assert len(plan) == 1 and plan[0]["provider"] == "glassnode"
    assert (plan[0]["params"]["s"], plan[0]["params"]["u"]) == (NOW - 10800, NOW)


def test_raw_envelope_clock_once_isolation_and_provider_failure():
    calls = 0
    source = coinglass()
    def clock():
        nonlocal calls
        calls += 1
        return NOW + 5
    def mixed(**kwargs):
        if kwargs["provider"] == "glassnode":
            raise RuntimeError("down")
        return source if kwargs["provider"] == "coinglass" else deribit()
    output = raw(fetcher=mixed, clock=clock)
    source["data"][0]["top_position_long_percent"] = 99
    assert calls == 1 and output["execution_timestamp"] == NOW + 5
    assert {item["status"] for item in output["requests"]} == {"ok", "error"}
    assert next(item for item in output["requests"] if item["provider"] == "coinglass")["response"]["data"][0]["top_position_long_percent"] == 52.15
    json.dumps(output, allow_nan=False)


def test_deribit_continuation_repeat_and_max_page_guards():
    calls = 0
    def paged(**kwargs):
        nonlocal calls
        calls += 1
        end = kwargs["params"]["params"]["end_timestamp"]
        return deribit(end // 1000, continuation=None if calls == 2 else end - 3_600_000)
    output = VolatilityMarketRegimesRawExtractor(paged, clock=lambda: NOW, deribit_max_pages=3).run(
        mode="recovery", reference_timestamp=NOW, recovery_requests=[{"provider": "deribit", "endpoint_id": "volatility_index",
            "start_timestamp": NOW - 10800, "end_timestamp": NOW - 3600}])
    assert len(output["requests"]) == 2 and calls == 2
    def repeated(**kwargs):
        return deribit(continuation=NOW * 1000)
    repeated_output = VolatilityMarketRegimesRawExtractor(repeated, clock=lambda: NOW).run(mode="incremental", reference_timestamp=NOW)
    deribit_requests = [item for item in repeated_output["requests"] if item["provider"] == "deribit"]
    assert len(deribit_requests) == 2 and "repeated_continuation_guard" in deribit_requests[-1]["warnings"]
    limited = VolatilityMarketRegimesRawExtractor(repeated, clock=lambda: NOW, deribit_max_pages=1).run(mode="incremental", reference_timestamp=NOW)
    assert "max_pages_guard" in next(item for item in limited["requests"] if item["provider"] == "deribit")["warnings"]
    assert DERIBIT_MAX_PAGES >= 2


@pytest.mark.parametrize("code", ["0", 0, "200", 200])
def test_coinglass_unwrap_codes_empty_and_errors(code):
    assert unwrap_coinglass_positioning_response({"code": code, "data": []}) == []
    with pytest.raises(ValueError, match="provider_error"):
        unwrap_coinglass_positioning_response({"code": 500, "data": []})
    with pytest.raises(ValueError, match="invalid_envelope"):
        unwrap_coinglass_positioning_response({"code": 0, "data": {}})


def test_coinglass_normalization_and_financial_consistency_without_recalculation():
    normalized = normalize_coinglass_positioning_record(coinglass()["data"][0])
    assert normalized == {"timestamp": NOW, "long_percent": 52.15, "short_percent": 47.85, "long_short_ratio": 1.09}
    for changes in ({"top_position_long_percent": 101}, {"top_position_short_percent": 40},
                    {"top_position_long_short_ratio": 2}, {"top_position_long_percent": True}):
        with pytest.raises(ValueError):
            normalize_coinglass_positioning_record(coinglass(**changes)["data"][0])


def test_glassnode_root_scale_negative_zero_and_invalid_values():
    assert unwrap_glassnode_realized_volatility_response(glassnode()) == glassnode()
    with pytest.raises(ValueError):
        unwrap_glassnode_realized_volatility_response({"data": []})
    assert normalize_glassnode_realized_volatility_record({"t": NOW, "v": .334}) == {
        "timestamp": NOW, "value_native": .334, "value_percent": 33.4}
    assert normalize_glassnode_realized_volatility_record({"t": NOW, "v": -0.0})["value_percent"] == 0.0
    for value in (True, -1, math.nan, math.inf):
        with pytest.raises(ValueError):
            normalize_glassnode_realized_volatility_record({"t": NOW, "v": value})


def test_deribit_envelope_candle_ohlc_and_scale():
    candle = unwrap_deribit_volatility_index_response(deribit())[0]
    normalized = normalize_deribit_volatility_index_record(candle)
    assert (normalized["timestamp"], normalized["open_percent"], normalized["close_percent"]) == (NOW, 48.1, 48.9)
    for response in ({"jsonrpc": "2.0", "error": {}}, {"result": {"data": []}}, {"jsonrpc": "2.0", "result": {"data": [], "continuation": "x"}}):
        with pytest.raises(ValueError):
            unwrap_deribit_volatility_index_response(response)
    for invalid in ([NOW * 1000, 1, 2], [NOW * 1000, .5, .4, .3, .6], [NOW * 1000, True, .5, .3, .4]):
        with pytest.raises(ValueError):
            normalize_deribit_volatility_index_record(invalid)


def test_upsert_deduplicate_order_replace_preserve_and_gaps():
    previous = [{"timestamp": NOW - 7200, "value": 1}, {"timestamp": NOW - 3600, "value": 2}]
    incoming = [{"timestamp": NOW - 3600, "value": 20}, {"timestamp": NOW, "value": 3}]
    output = upsert_timestamp_records(previous, incoming)
    assert output == [{"timestamp": NOW - 7200, "value": 1}, {"timestamp": NOW - 3600, "value": 20}, {"timestamp": NOW, "value": 3}]
    assert detect_hourly_gaps(output) == {"gap_count": 0, "gap_ranges": []}
    gap = detect_hourly_gaps([output[0], output[-1]])
    assert gap == {"gap_count": 1, "gap_ranges": [{"after_timestamp": NOW - 7200,
        "before_timestamp": NOW, "missing_intervals": 1}]}


def test_complete_preprocessing_shape_available_quality_and_strict_json():
    source = raw()
    before = copy.deepcopy(source)
    output = preprocess_volatility_market_regimes_input(source)
    assert source == before
    assert tuple(output["providers"]) == ("coinglass", "glassnode", "deribit")
    assert output["quality"]["status"] == "ok"
    assert output["quality"]["required_datasets"] == ["coinglass.top_position_ratio", "glassnode.realized_volatility", "deribit.volatility_index"]
    for provider, name in (("coinglass", "top_position_ratio"), ("glassnode", "realized_volatility"), ("deribit", "volatility_index")):
        dataset = output["providers"][provider][name]
        assert dataset["status"] == "available" and dataset["reason"] is None
        assert dataset["records_available"] == 1 and dataset["source_data_as_of"] == NOW
        assert dataset["provenance"]["provider"] == provider
    json.dumps(output, ensure_ascii=False, allow_nan=False)
    assert all(forbidden not in key.lower() for provider in output["providers"].values() for dataset in provider.values()
        for key in dataset for forbidden in ("spread", "regime", "confidence", "signal"))


def test_chunks_pages_deduplicate_with_latest_request_winning():
    bundle = raw(bootstrap_history_days=120)
    cg = [item for item in bundle["requests"] if item["provider"] == "coinglass"]
    assert len(cg) == 3
    for index, item in enumerate(cg):
        item["response"] = coinglass(NOW, top_position_long_percent=52 + index * .05,
            top_position_short_percent=48 - index * .05, top_position_long_short_ratio=(52 + index * .05) / (48 - index * .05))
    output = preprocess_volatility_market_regimes_input(bundle)
    records = output["providers"]["coinglass"]["top_position_ratio"]["incoming_records"]
    assert len(records) == 1 and records[0]["long_percent"] == 52.1


def test_empty_failure_invalid_partial_gap_and_stale_availability():
    bundle = raw()
    for request in bundle["requests"]:
        if request["provider"] == "coinglass":
            request["response"] = {"code": "0", "data": []}
        elif request["provider"] == "glassnode":
            request.update(status="error", response=None, error="down")
        else:
            request["response"] = {"bad": True}
    output = preprocess_volatility_market_regimes_input(bundle)
    assert (output["providers"]["coinglass"]["top_position_ratio"]["status"],
            output["providers"]["coinglass"]["top_position_ratio"]["reason"]) == ("unavailable", "empty_response")
    assert output["providers"]["glassnode"]["realized_volatility"]["reason"] == "request_failed"
    assert output["providers"]["deribit"]["volatility_index"]["reason"] == "invalid_envelope"
    assert output["quality"]["status"] == "invalid"
    assert all(dataset["reason"] for provider in output["providers"].values() for dataset in provider.values() if dataset["status"] != "available")
    stale = raw(reference_timestamp=NOW + 10800)
    for request in stale["requests"]:
        if request["provider"] == "coinglass":
            request["response"] = coinglass(NOW)
        elif request["provider"] == "glassnode":
            request["response"] = glassnode(NOW)
        else:
            request["response"] = deribit(NOW)
    stale_output = preprocess_volatility_market_regimes_input(stale)
    assert all(dataset["reason"] == "stale_latest_record" for provider in stale_output["providers"].values() for dataset in provider.values())


def test_incremental_failure_and_invalid_preserve_previous_without_mutation():
    previous = preprocess_volatility_market_regimes_input(raw())
    before = copy.deepcopy(previous)
    failed = raw(mode="incremental")
    for request in failed["requests"]:
        request.update(status="error", response=None, error="down")
    output = preprocess_volatility_market_regimes_input(failed, existing_contract=previous)
    assert previous == before and output["quality"]["status"] == "partial"
    assert all(dataset["reason"] == "latest_refresh_failed" and dataset["records"]
        for provider in output["providers"].values() for dataset in provider.values())
    invalid = raw(mode="incremental")
    for request in invalid["requests"]:
        request["response"] = {"bad": True}
    invalid_output = preprocess_volatility_market_regimes_input(invalid, existing_contract=previous)
    assert all(dataset["reason"] == "latest_attempt_invalid" for provider in invalid_output["providers"].values() for dataset in provider.values())


def test_recovery_preserves_non_targets_and_quality_targets_only():
    previous = preprocess_volatility_market_regimes_input(raw())
    request = {"provider": "glassnode", "endpoint_id": "realized_volatility", "start_timestamp": NOW - 7200, "end_timestamp": NOW - 3600}
    recovery = raw(mode="recovery", recovery_requests=[request])
    output = preprocess_volatility_market_regimes_input(recovery, existing_contract=previous)
    assert output["providers"]["coinglass"] == previous["providers"]["coinglass"]
    assert output["providers"]["deribit"] == previous["providers"]["deribit"]
    assert output["quality"]["required_datasets"] == ["glassnode.realized_volatility"]


def test_mode_determination_requires_real_history():
    assert determine_volatility_market_regimes_input_mode(existing_contract={"providers": {}}) == "bootstrap"
    previous = preprocess_volatility_market_regimes_input(raw())
    assert determine_volatility_market_regimes_input_mode(existing_contract=previous) == "incremental"
    assert determine_volatility_market_regimes_input_mode(existing_contract=previous,
        recovery_requests=[{}]) == "recovery"
    with pytest.raises(ValueError):
        determine_volatility_market_regimes_input_mode(requested_mode="recovery", recovery_requests=[])


def test_nan_in_raw_never_reaches_preprocessed_output():
    bundle = raw()
    next(item for item in bundle["requests"] if item["provider"] == "glassnode")["response"] = [{"t": NOW, "v": math.nan}]
    output = preprocess_volatility_market_regimes_input(bundle)
    assert output["providers"]["glassnode"]["realized_volatility"]["status"] == "invalid"
    json.dumps(output, allow_nan=False)
