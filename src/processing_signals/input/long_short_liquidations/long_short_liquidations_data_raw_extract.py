"""Raw extraction contract for the long/short liquidations input family."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import time
from typing import Any

LONG_SHORT_LIQUIDATIONS_FAMILY = "long_short_liquidations"
COINGLASS_PROVIDER = "coinglass"
CRYPTOQUANT_PROVIDER = "cryptoquant"
GLASSNODE_PROVIDER = "glassnode"
VALID_MODES = {"bootstrap", "incremental", "recovery"}
DEFAULT_ASSET = "BTC"
DEFAULT_INTERVAL = "1h"
DEFAULT_HISTORY_HOURS = 72
DEFAULT_INCREMENTAL_OVERLAP_H = 6
DEFAULT_EVENT_LOOKBACK_H = 24
DEFAULT_EVENT_OVERLAP_MINUTES = 15
DEFAULT_MIN_EVENT_USD = 10_000
DEFAULT_MAP_RANGE = "1d"
DEFAULT_EXCHANGE_RANGE = "24h"
DEFAULT_MAX_PAIN_RANGE = "24h"
DEFAULT_EXCHANGES = ("Binance", "OKX", "Bybit", "Hyperliquid")
DEFAULT_CRYPTOQUANT_EXCHANGES = ("binance", "bybit", "okx")
GLASSNODE_LONG_LIQUIDATIONS_ENDPOINT_ID = "glassnode_long_liquidations"
GLASSNODE_SHORT_LIQUIDATIONS_ENDPOINT_ID = "glassnode_short_liquidations"
GLASSNODE_TOTAL_LIQUIDATIONS_ENDPOINT_ID = "glassnode_total_liquidations"
GLASSNODE_LONG_LIQUIDATION_DOMINANCE_ENDPOINT_ID = "glassnode_long_liquidation_dominance"

RawFetcher = Callable[..., Any]
Clock = Callable[[], int | float]

ENDPOINT_MANIFEST: dict[tuple[str, str], str] = {
    (COINGLASS_PROVIDER, "supported_exchange_pairs"): "/api/futures/supported-exchange-pairs",
    (COINGLASS_PROVIDER, "aggregated_liquidation_history"): "/api/futures/liquidation/aggregated-history",
    (COINGLASS_PROVIDER, "liquidation_exchange_list"): "/api/futures/liquidation/exchange-list",
    (COINGLASS_PROVIDER, "pair_liquidation_history"): "/api/futures/liquidation/history",
    (COINGLASS_PROVIDER, "liquidation_order_events"): "/api/futures/liquidation/order",
    (COINGLASS_PROVIDER, "aggregated_liquidation_map"): "/api/futures/liquidation/aggregated-map",
    (COINGLASS_PROVIDER, "pair_liquidation_map"): "/api/futures/liquidation/map",
    (COINGLASS_PROVIDER, "liquidation_max_pain"): "/api/futures/liquidation/max-pain",
    (CRYPTOQUANT_PROVIDER, "cryptoquant_liquidations"): "/btc/market-data/liquidations",
    (GLASSNODE_PROVIDER, GLASSNODE_LONG_LIQUIDATIONS_ENDPOINT_ID): "/v1/metrics/derivatives/futures_liquidated_volume_long_sum",
    (GLASSNODE_PROVIDER, GLASSNODE_SHORT_LIQUIDATIONS_ENDPOINT_ID): "/v1/metrics/derivatives/futures_liquidated_volume_short_sum",
    (GLASSNODE_PROVIDER, GLASSNODE_TOTAL_LIQUIDATIONS_ENDPOINT_ID): "/v1/metrics/derivatives/futures_liquidated_total_volume_sum",
    (GLASSNODE_PROVIDER, GLASSNODE_LONG_LIQUIDATION_DOMINANCE_ENDPOINT_ID): "/v1/metrics/derivatives/futures_liquidated_volume_long_relative",
}


def _request(provider: str, endpoint_id: str, params: Mapping[str, Any], suffix: str = "",
             dimensions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    path = ENDPOINT_MANIFEST[(provider, endpoint_id)]
    identity = suffix or ":".join(str(value) for value in params.values())
    return {
        "request_id": f"{provider}:{endpoint_id}:{identity}",
        "provider": provider,
        "endpoint_id": endpoint_id,
        "path": path,
        "params": deepcopy(dict(params)),
        "dimensions": deepcopy(dict(dimensions or {})),
    }


def _window(reference_timestamp: int, hours: int) -> tuple[int, int]:
    return reference_timestamp - hours * 3600, reference_timestamp


def build_long_short_liquidations_fetch_plan(
    *,
    mode: str,
    reference_timestamp: int,
    asset: str = DEFAULT_ASSET,
    exchanges: Sequence[str] = DEFAULT_EXCHANGES,
    exchange_pairs: Mapping[str, str] | None = None,
    cryptoquant_exchanges: Sequence[str] | None = None,
    history_hours: int = DEFAULT_HISTORY_HOURS,
    incremental_overlap_hours: int = DEFAULT_INCREMENTAL_OVERLAP_H,
    event_lookback_hours: int = DEFAULT_EVENT_LOOKBACK_H,
    event_overlap_minutes: int = DEFAULT_EVENT_OVERLAP_MINUTES,
    event_cursors: Mapping[str, int] | None = None,
    min_event_usd: int | float = DEFAULT_MIN_EVENT_USD,
    map_range: str = DEFAULT_MAP_RANGE,
    exchange_range: str = DEFAULT_EXCHANGE_RANGE,
    max_pain_range: str = DEFAULT_MAX_PAIN_RANGE,
    recovery_requests: Sequence[Mapping[str, Any]] | None = None,
    refresh_discovery: bool = False,
) -> list[dict[str, Any]]:
    """Build the deterministic endpoint plan without performing I/O."""
    if mode not in VALID_MODES:
        raise ValueError(f"unsupported_mode:{mode}")
    if mode == "recovery":
        if not recovery_requests:
            raise ValueError("recovery_requests_required")
        plan = []
        for item in recovery_requests or ():
            if not isinstance(item, Mapping):
                raise ValueError("recovery_request_must_be_mapping")
            provider = item.get("provider")
            endpoint_id = item.get("endpoint_id")
            if (provider, endpoint_id) not in ENDPOINT_MANIFEST:
                raise ValueError(f"unsupported_recovery_endpoint:{provider}:{endpoint_id}")
            params = item.get("params")
            if not isinstance(params, Mapping):
                raise ValueError("recovery_params_must_be_mapping")
            dimensions = item.get("dimensions", {})
            if not isinstance(dimensions, Mapping):
                raise ValueError("recovery_dimensions_must_be_mapping")
            inferred_dimensions = {"exchange": params.get("exchange"), "asset": asset,
                                   "symbol": params.get("symbol", params.get("a"))}
            inferred_dimensions.update(dimensions)
            plan.append(_request(provider, endpoint_id, params, str(item.get("request_id", "recovery")),
                                 inferred_dimensions))
        return plan

    pairs = dict(exchange_pairs or {})
    cq_exchanges = (DEFAULT_CRYPTOQUANT_EXCHANGES if cryptoquant_exchanges is None else
                    tuple(cryptoquant_exchanges))
    history_window = history_hours if mode == "bootstrap" else incremental_overlap_hours
    start, end = _window(reference_timestamp, history_window)
    limit = max(1, history_window)
    plan: list[dict[str, Any]] = []
    if mode == "bootstrap" or refresh_discovery:
        plan.append(_request(COINGLASS_PROVIDER, "supported_exchange_pairs", {}, "all",
                             {"exchange": None, "asset": asset, "symbol": None}))
    plan.append(_request(COINGLASS_PROVIDER, "aggregated_liquidation_history", {
        "exchange_list": ",".join(exchanges), "symbol": asset, "interval": DEFAULT_INTERVAL,
        "limit": limit, "start_time": start * 1000, "end_time": end * 1000,
    }, f"{asset}:{DEFAULT_INTERVAL}:{start}:{end}",
        {"exchange": None, "asset": asset, "symbol": asset}))
    plan.append(_request(COINGLASS_PROVIDER, "liquidation_exchange_list", {
        "symbol": asset, "range": exchange_range,
    }, f"{asset}:{exchange_range}", {"exchange": None, "asset": asset, "symbol": asset}))
    for exchange in exchanges:
        pair = pairs.get(exchange)
        if pair:
            plan.append(_request(COINGLASS_PROVIDER, "pair_liquidation_history", {
                "exchange": exchange, "symbol": pair, "interval": DEFAULT_INTERVAL,
                "limit": limit, "start_time": start * 1000, "end_time": end * 1000,
            }, f"{exchange}:{pair}:{start}:{end}",
                {"exchange": exchange, "asset": asset, "symbol": pair}))
        else:
            plan.append({
                **_request(COINGLASS_PROVIDER, "pair_liquidation_history", {}, f"{exchange}:skipped",
                           {"exchange": exchange, "asset": asset, "symbol": None}),
                "skip_reason": "pair_symbol_not_configured",
            })
        cursor = (event_cursors or {}).get(exchange)
        if cursor is not None:
            event_start = cursor - event_overlap_minutes * 60
        elif mode == "incremental":
            event_start = end - event_overlap_minutes * 60
        else:
            event_start = end - event_lookback_hours * 3600
        plan.append(_request(COINGLASS_PROVIDER, "liquidation_order_events", {
            "exchange": exchange, "symbol": asset,
            "min_liquidation_amount": f"{min_event_usd:g}",
            "start_time": event_start * 1000, "end_time": end * 1000,
        }, f"{exchange}:{event_start}:{end}",
            {"exchange": exchange, "asset": asset, "symbol": asset}))
    plan.append(_request(COINGLASS_PROVIDER, "aggregated_liquidation_map", {
        "symbol": asset, "range": map_range,
    }, f"{asset}:{map_range}", {"exchange": None, "asset": asset, "symbol": asset}))
    for exchange in exchanges:
        pair = pairs.get(exchange)
        if pair:
            plan.append(_request(COINGLASS_PROVIDER, "pair_liquidation_map", {
                "exchange": exchange, "symbol": pair, "range": map_range,
            }, f"{exchange}:{pair}:{map_range}",
                {"exchange": exchange, "asset": asset, "symbol": pair}))
        else:
            plan.append({
                **_request(COINGLASS_PROVIDER, "pair_liquidation_map", {}, f"{exchange}:skipped",
                           {"exchange": exchange, "asset": asset, "symbol": None}),
                "skip_reason": "pair_symbol_not_configured",
            })
    plan.append(_request(COINGLASS_PROVIDER, "liquidation_max_pain", {
        "range": max_pain_range,
    }, max_pain_range, {"exchange": None, "asset": asset, "symbol": asset}))
    cq_common = {"window": "hour", "from": start, "to": end, "limit": limit, "format": "json"}
    plan.append(_request(CRYPTOQUANT_PROVIDER, "cryptoquant_liquidations", {
        "exchange": "all_exchange", "symbol": "all_symbol", **cq_common,
    }, f"aggregate:{start}:{end}",
        {"exchange": "all_exchange", "asset": asset, "symbol": "all_symbol"}))
    for exchange in cq_exchanges:
        if exchange not in DEFAULT_CRYPTOQUANT_EXCHANGES:
            continue
        plan.append(_request(CRYPTOQUANT_PROVIDER, "cryptoquant_liquidations", {
            "exchange": exchange, "symbol": "btc_usdt", **cq_common,
        }, f"{exchange}:{start}:{end}",
            {"exchange": exchange, "asset": asset, "symbol": "btc_usdt"}))
    for endpoint_id in (
        GLASSNODE_LONG_LIQUIDATIONS_ENDPOINT_ID,
        GLASSNODE_SHORT_LIQUIDATIONS_ENDPOINT_ID,
        GLASSNODE_TOTAL_LIQUIDATIONS_ENDPOINT_ID,
        GLASSNODE_LONG_LIQUIDATION_DOMINANCE_ENDPOINT_ID,
    ):
        params = {"a": asset, "s": start, "u": end, "i": DEFAULT_INTERVAL, "f": "json", "timestamp_format": "unix"}
        if endpoint_id != GLASSNODE_LONG_LIQUIDATION_DOMINANCE_ENDPOINT_ID:
            params["c"] = "USD"
        plan.append(_request(GLASSNODE_PROVIDER, endpoint_id, params, f"{asset}:{start}:{end}",
                             {"exchange": None, "asset": asset, "symbol": asset}))
    return plan


def execute_raw_request(*, fetcher: RawFetcher, request: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one request and isolate all endpoint failures."""
    base = {key: deepcopy(request[key]) for key in
            ("request_id", "provider", "endpoint_id", "path", "params", "dimensions")}
    if request.get("skip_reason"):
        return {**base, "status": "skipped", "response": None, "error": None, "warnings": [request["skip_reason"]]}
    try:
        response = fetcher(
            provider=request["provider"], endpoint_id=request["endpoint_id"],
            path=request["path"], params=deepcopy(request["params"]),
        )
        return {**base, "status": "ok", "response": deepcopy(response), "error": None, "warnings": []}
    except Exception as exc:  # endpoint isolation is part of the Raw contract
        return {**base, "status": "error", "response": None, "error": f"{type(exc).__name__}:{exc}", "warnings": []}


def _event_rows(response: Any) -> list[Any] | None:
    if not isinstance(response, Mapping):
        return None
    data = response.get("data")
    return data if isinstance(data, list) else None


def _execute_event_window(
    *, fetcher: RawFetcher, request: Mapping[str, Any], minimum_event_window_seconds: int,
) -> list[dict[str, Any]]:
    result = execute_raw_request(fetcher=fetcher, request=request)
    rows = _event_rows(result.get("response")) if result["status"] == "ok" else None
    if rows is None or len(rows) < 200:
        return [result]
    params = request["params"]
    start_ms, end_ms = params["start_time"], params["end_time"]
    if end_ms - start_ms <= minimum_event_window_seconds * 1000:
        result["warnings"].append("event_endpoint_record_limit_reached")
        return [result]
    midpoint = (start_ms + end_ms) // 2
    children = []
    for child_start, child_end in ((start_ms, midpoint), (midpoint, end_ms)):
        child = deepcopy(dict(request))
        child["params"]["start_time"] = child_start
        child["params"]["end_time"] = child_end
        child["request_id"] = f"{request['provider']}:{request['endpoint_id']}:{params['exchange']}:{child_start}:{child_end}"
        children.extend(_execute_event_window(
            fetcher=fetcher, request=child, minimum_event_window_seconds=minimum_event_window_seconds,
        ))
    return children


def extract_long_short_liquidations_raw(
    *, fetcher: RawFetcher, mode: str, reference_timestamp: int,
    execution_timestamp: int | None = None, minimum_event_window_seconds: int = 60, **plan_options: Any,
) -> dict[str, Any]:
    """Build and execute a Raw bundle while preserving every response."""
    executed_at = int(time.time()) if execution_timestamp is None else execution_timestamp
    plan = build_long_short_liquidations_fetch_plan(
        mode=mode, reference_timestamp=reference_timestamp, **plan_options,
    )
    results: list[dict[str, Any]] = []
    for request in plan:
        if request["endpoint_id"] == "liquidation_order_events" and not request.get("skip_reason"):
            results.extend(_execute_event_window(
                fetcher=fetcher, request=request, minimum_event_window_seconds=minimum_event_window_seconds,
            ))
        else:
            results.append(execute_raw_request(fetcher=fetcher, request=request))
    return {
        "family": LONG_SHORT_LIQUIDATIONS_FAMILY, "stage": "input_raw", "mode": mode,
        "reference_timestamp": reference_timestamp, "execution_timestamp": executed_at,
        "requests": results,
    }


class LongShortLiquidationsRawExtractor:
    """Configured facade around plan construction and isolated execution."""

    def __init__(
        self, *, fetcher: RawFetcher, asset: str = DEFAULT_ASSET,
        exchanges: Sequence[str] = DEFAULT_EXCHANGES, exchange_pairs: Mapping[str, str] | None = None,
        cryptoquant_exchanges: Sequence[str] | None = None, reference_timestamp: int | None = None,
        clock: Clock | None = None, history_hours: int = DEFAULT_HISTORY_HOURS,
        incremental_overlap_hours: int = DEFAULT_INCREMENTAL_OVERLAP_H,
        event_lookback_hours: int = DEFAULT_EVENT_LOOKBACK_H,
        event_overlap_minutes: int = DEFAULT_EVENT_OVERLAP_MINUTES,
        min_event_usd: int | float = DEFAULT_MIN_EVENT_USD, map_range: str = DEFAULT_MAP_RANGE,
        exchange_range: str = DEFAULT_EXCHANGE_RANGE, max_pain_range: str = DEFAULT_MAX_PAIN_RANGE,
        minimum_event_window_seconds: int = 60,
    ) -> None:
        self.fetcher = fetcher
        self.asset = asset
        self.exchanges = tuple(exchanges)
        self.exchange_pairs = deepcopy(dict(exchange_pairs or {}))
        self.cryptoquant_exchanges = (DEFAULT_CRYPTOQUANT_EXCHANGES if cryptoquant_exchanges is None else
                                     tuple(cryptoquant_exchanges))
        self.clock = clock or time.time
        self.reference_timestamp = reference_timestamp
        self.history_hours = history_hours
        self.incremental_overlap_hours = incremental_overlap_hours
        self.event_lookback_hours = event_lookback_hours
        self.event_overlap_minutes = event_overlap_minutes
        self.min_event_usd = min_event_usd
        self.map_range = map_range
        self.exchange_range = exchange_range
        self.max_pain_range = max_pain_range
        self.minimum_event_window_seconds = minimum_event_window_seconds

    def _options(self) -> dict[str, Any]:
        return {
            "asset": self.asset, "exchanges": self.exchanges, "exchange_pairs": self.exchange_pairs,
            "cryptoquant_exchanges": self.cryptoquant_exchanges, "history_hours": self.history_hours,
            "incremental_overlap_hours": self.incremental_overlap_hours,
            "event_lookback_hours": self.event_lookback_hours,
            "event_overlap_minutes": self.event_overlap_minutes, "min_event_usd": self.min_event_usd,
            "map_range": self.map_range, "exchange_range": self.exchange_range,
            "max_pain_range": self.max_pain_range,
        }

    def build_fetch_plan(self, *, mode: str, recovery_requests: Sequence[Mapping[str, Any]] | None = None,
                         event_cursors: Mapping[str, int] | None = None,
                         refresh_discovery: bool = False) -> list[dict[str, Any]]:
        reference = int(self.clock()) if self.reference_timestamp is None else self.reference_timestamp
        return build_long_short_liquidations_fetch_plan(
            mode=mode, reference_timestamp=reference, recovery_requests=recovery_requests,
            event_cursors=event_cursors, refresh_discovery=refresh_discovery, **self._options(),
        )

    def run(self, *, mode: str, recovery_requests: Sequence[Mapping[str, Any]] | None = None,
            event_cursors: Mapping[str, int] | None = None,
            refresh_discovery: bool = False) -> dict[str, Any]:
        execution = int(self.clock())
        reference = execution if self.reference_timestamp is None else self.reference_timestamp
        return extract_long_short_liquidations_raw(
            fetcher=self.fetcher, mode=mode, reference_timestamp=reference,
            execution_timestamp=execution, minimum_event_window_seconds=self.minimum_event_window_seconds,
            recovery_requests=recovery_requests, event_cursors=event_cursors,
            refresh_discovery=refresh_discovery, **self._options(),
        )
