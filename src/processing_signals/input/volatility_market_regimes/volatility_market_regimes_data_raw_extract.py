"""Injectable raw extraction for Volatility Market Regimes Input v0.1."""
from __future__ import annotations

import copy
import math
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

VOLATILITY_MARKET_REGIMES_FAMILY       = "volatility_market_regimes"
COINGLASS_PROVIDER                     = "coinglass"
GLASSNODE_PROVIDER                     = "glassnode"
DERIBIT_PROVIDER                       = "deribit"
COINGLASS_POSITIONING_ENDPOINT_ID      = "top_position_long_short_ratio"
GLASSNODE_REALIZED_VOL_ENDPOINT_ID     = "realized_volatility"
DERIBIT_VOLATILITY_INDEX_ENDPOINT_ID   = "volatility_index"
BASE_INTERVAL                          = "1h"
INTERVAL_SECONDS                       = 3600
BOOTSTRAP_HISTORY_DAYS                 = 120
INCREMENTAL_HOURS                      = 12
COINGLASS_MAX_LIMIT                    = 1000
DERIBIT_MAX_PAGES                      = 100
VALID_MODES                            = {"bootstrap", "incremental", "recovery"}

ENDPOINT_MANIFEST = {
    (COINGLASS_PROVIDER, COINGLASS_POSITIONING_ENDPOINT_ID): "/api/futures/top-long-short-position-ratio/history",
    (GLASSNODE_PROVIDER, GLASSNODE_REALIZED_VOL_ENDPOINT_ID): "/v1/metrics/market/realized_volatility_1_week",
    (DERIBIT_PROVIDER, DERIBIT_VOLATILITY_INDEX_ENDPOINT_ID): "/api/v2/public/get_volatility_index_data",
}
ENDPOINT_NORMALIZATION = {
    (COINGLASS_PROVIDER, COINGLASS_POSITIONING_ENDPOINT_ID): {"timestamp_unit": "milliseconds", "value_scale": "provider_percent"},
    (GLASSNODE_PROVIDER, GLASSNODE_REALIZED_VOL_ENDPOINT_ID): {"timestamp_unit": "seconds", "value_scale": "fraction_to_percent"},
    (DERIBIT_PROVIDER, DERIBIT_VOLATILITY_INDEX_ENDPOINT_ID): {"timestamp_unit": "milliseconds", "value_scale": "fraction_to_percent"},
}

VolatilityMarketRegimesFetcher = Callable[..., Mapping[str, Any] | Sequence[Any]]


def _timestamp(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name}_must_be_non_negative_int")
    return value


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name}_must_be_positive_int")
    return value


def _clock(clock: Callable[[], Any] | None) -> int:
    value = time.time() if clock is None else clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid_clock")
    return int(value)


def build_coinglass_positioning_params(*, start_timestamp: int, end_timestamp: int, limit: int) -> dict[str, Any]:
    start, end, size = _timestamp(start_timestamp, "start_timestamp"), _timestamp(end_timestamp, "end_timestamp"), _positive_int(limit, "limit")
    if start >= end or size > COINGLASS_MAX_LIMIT:
        raise ValueError("invalid_coinglass_window")
    return {"exchange": "Binance", "symbol": "BTCUSDT", "interval": BASE_INTERVAL, "limit": size,
        "start_time": start * 1000, "end_time": end * 1000}


def build_glassnode_realized_volatility_params(*, start_timestamp: int, end_timestamp: int) -> dict[str, Any]:
    start, end = _timestamp(start_timestamp, "start_timestamp"), _timestamp(end_timestamp, "end_timestamp")
    if start >= end:
        raise ValueError("invalid_glassnode_window")
    return {"a": "BTC", "s": start, "u": end, "i": BASE_INTERVAL, "f": "json", "timestamp_format": "unix"}


def build_deribit_volatility_index_params(*, start_timestamp: int, end_timestamp: int, request_id: int = 1) -> dict[str, Any]:
    start, end = _timestamp(start_timestamp, "start_timestamp"), _timestamp(end_timestamp, "end_timestamp")
    if start >= end or type(request_id) is not int:
        raise ValueError("invalid_deribit_window")
    return {"jsonrpc": "2.0", "id": request_id, "method": "public/get_volatility_index_data",
        "params": {"currency": "BTC", "start_timestamp": start * 1000, "end_timestamp": end * 1000, "resolution": "3600"}}


def _instruction(provider: str, endpoint_id: str, start: int, end: int, page: int = 1,
                 *, coinglass_limit: int | None = None) -> dict[str, Any]:
    key = (provider, endpoint_id)
    if provider == COINGLASS_PROVIDER:
        params = build_coinglass_positioning_params(start_timestamp=start, end_timestamp=end, limit=coinglass_limit or 1)
        dimensions = {"exchange": "Binance", "symbol": "BTCUSDT", "interval": BASE_INTERVAL}
    elif provider == GLASSNODE_PROVIDER:
        params = build_glassnode_realized_volatility_params(start_timestamp=start, end_timestamp=end)
        dimensions = {"asset": "BTC", "interval": BASE_INTERVAL}
    else:
        params = build_deribit_volatility_index_params(start_timestamp=start, end_timestamp=end, request_id=page)
        dimensions = {"currency": "BTC", "resolution": "3600", "interval": BASE_INTERVAL}
    return {"request_id": f"{provider}:{endpoint_id}:{start}:{end}:page:{page:04d}", "provider": provider,
        "endpoint_id": endpoint_id, "path": ENDPOINT_MANIFEST[key], "params": params, "dimensions": dimensions,
        "normalization": copy.deepcopy(ENDPOINT_NORMALIZATION[key])}


def _coinglass_chunks(start: int, end: int) -> list[dict[str, Any]]:
    output, cursor, page = [], start, 1
    while cursor < end:
        chunk_end = min(end, cursor + (COINGLASS_MAX_LIMIT - 1) * INTERVAL_SECONDS)
        limit = (chunk_end - cursor) // INTERVAL_SECONDS + 1
        output.append(_instruction(COINGLASS_PROVIDER, COINGLASS_POSITIONING_ENDPOINT_ID, cursor, chunk_end, page, coinglass_limit=limit))
        if chunk_end == end:
            break
        cursor, page = chunk_end, page + 1
    return output


def build_volatility_market_regimes_fetch_plan(*, mode: str, reference_timestamp: int,
                                               recovery_requests: Sequence[Mapping[str, Any]] | None = None,
                                               bootstrap_history_days: int = BOOTSTRAP_HISTORY_DAYS,
                                               incremental_hours: int = INCREMENTAL_HOURS) -> list[dict[str, Any]]:
    if mode not in VALID_MODES:
        raise ValueError("unsupported_mode")
    reference = _timestamp(reference_timestamp, "reference_timestamp")
    if mode == "recovery":
        if not isinstance(recovery_requests, Sequence) or isinstance(recovery_requests, (str, bytes, bytearray)) or not recovery_requests:
            raise ValueError("recovery_requests_required")
        output = []
        for target in recovery_requests:
            if not isinstance(target, Mapping):
                raise ValueError("invalid_recovery_request")
            provider, endpoint = target.get("provider"), target.get("endpoint_id")
            if (provider, endpoint) not in ENDPOINT_MANIFEST:
                raise ValueError("unknown_recovery_target")
            start, end = _timestamp(target.get("start_timestamp"), "start_timestamp"), _timestamp(target.get("end_timestamp"), "end_timestamp")
            if start >= end:
                raise ValueError("invalid_recovery_range")
            padded_start, padded_end = max(0, start - INTERVAL_SECONDS), end + INTERVAL_SECONDS
            if provider == COINGLASS_PROVIDER:
                output.extend(_coinglass_chunks(padded_start, padded_end))
            else:
                output.append(_instruction(provider, endpoint, padded_start, padded_end))
        return output
    duration = _positive_int(bootstrap_history_days if mode == "bootstrap" else incremental_hours,
                             "history") * (86400 if mode == "bootstrap" else INTERVAL_SECONDS)
    start = max(0, reference - duration)
    return [*_coinglass_chunks(start, reference),
        _instruction(GLASSNODE_PROVIDER, GLASSNODE_REALIZED_VOL_ENDPOINT_ID, start, reference),
        _instruction(DERIBIT_PROVIDER, DERIBIT_VOLATILITY_INDEX_ENDPOINT_ID, start, reference)]


class VolatilityMarketRegimesRawExtractor:
    def __init__(self, fetcher: VolatilityMarketRegimesFetcher, *, clock: Callable[[], Any] | None = None,
                 deribit_max_pages: int = DERIBIT_MAX_PAGES) -> None:
        self.fetcher, self.clock = fetcher, clock
        self.deribit_max_pages = _positive_int(deribit_max_pages, "deribit_max_pages")

    def build_fetch_plan(self, **kwargs: Any) -> list[dict[str, Any]]:
        return build_volatility_market_regimes_fetch_plan(**kwargs)

    def execute_request(self, instruction: Mapping[str, Any]) -> dict[str, Any]:
        request = copy.deepcopy(dict(instruction))
        try:
            response = self.fetcher(provider=request["provider"], endpoint_id=request["endpoint_id"],
                path=request["path"], params=copy.deepcopy(request["params"]))
            request.update(status="ok", response=copy.deepcopy(response), error=None, warnings=[])
        except Exception as exc:
            request.update(status="error", response=None, error=f"{type(exc).__name__}: {exc}", warnings=[])
        return request

    def run(self, *, mode: str, reference_timestamp: int, recovery_requests: Sequence[Mapping[str, Any]] | None = None,
            bootstrap_history_days: int = BOOTSTRAP_HISTORY_DAYS, incremental_hours: int = INCREMENTAL_HOURS) -> dict[str, Any]:
        execution_timestamp = _clock(self.clock)
        plan = self.build_fetch_plan(mode=mode, reference_timestamp=reference_timestamp, recovery_requests=recovery_requests,
            bootstrap_history_days=bootstrap_history_days, incremental_hours=incremental_hours)
        requests = []
        for instruction in plan:
            executed = self.execute_request(instruction)
            requests.append(executed)
            if executed["provider"] != DERIBIT_PROVIDER or executed["status"] != "ok":
                continue
            seen, page = set(), 1
            while isinstance(executed.get("response"), Mapping):
                continuation = executed["response"].get("result", {}).get("continuation") if isinstance(executed["response"].get("result"), Mapping) else None
                if continuation is None:
                    break
                if type(continuation) is not int:
                    executed["warnings"].append("invalid_continuation_guard")
                    break
                if continuation in seen:
                    executed["warnings"].append("repeated_continuation_guard")
                    break
                seen.add(continuation)
                if page >= self.deribit_max_pages:
                    executed["warnings"].append("max_pages_guard")
                    break
                page += 1
                nested = instruction["params"]["params"]
                start_seconds, end_seconds = nested["start_timestamp"] // 1000, continuation // 1000
                next_instruction = _instruction(DERIBIT_PROVIDER, DERIBIT_VOLATILITY_INDEX_ENDPOINT_ID,
                    start_seconds, end_seconds, page)
                executed = self.execute_request(next_instruction)
                requests.append(executed)
                if executed["status"] != "ok":
                    break
        return {"family": VOLATILITY_MARKET_REGIMES_FAMILY, "stage": "input_raw", "mode": mode,
            "reference_timestamp": _timestamp(reference_timestamp, "reference_timestamp"),
            "execution_timestamp": execution_timestamp, "requests": requests}


def extract_volatility_market_regimes_raw(*, fetcher: VolatilityMarketRegimesFetcher, mode: str,
                                          reference_timestamp: int, recovery_requests: Sequence[Mapping[str, Any]] | None = None,
                                          clock: Callable[[], Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return VolatilityMarketRegimesRawExtractor(fetcher, clock=clock).run(mode=mode, reference_timestamp=reference_timestamp,
        recovery_requests=recovery_requests, **kwargs)
