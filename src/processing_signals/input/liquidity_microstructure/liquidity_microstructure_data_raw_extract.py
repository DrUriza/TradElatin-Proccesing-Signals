"""Deterministic CoinGlass extraction plan for Liquidity Microstructure Input v0.1."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import time
from typing import Any

LIQUIDITY_MICROSTRUCTURE_FAMILY = "liquidity_microstructure"
PROVIDER                         = "coinglass"
REST_BASE_URL                    = "https://open-api-v4.coinglass.com"
WEBSOCKET_BASE_URL               = "wss://open-ws.coinglass.com/ws-api"
TIMEFRAMES                       = ("1m", "5m", "15m", "1h")
DEPTH_RANGES_PERCENT             = (1, 5, 10)
VALID_MODES                      = {"bootstrap", "incremental", "recovery"}

ENDPOINT_MANIFEST = {
    "spot_orderbook_heatmap": {"transport": "rest", "path": "/api/spot/orderbook/history"},
    "perpetual_orderbook_heatmap": {"transport": "rest", "path": "/api/futures/orderbook/history"},
    "spot_order_depth": {"transport": "rest", "path": "/api/spot/orderbook/ask-bids-history"},
    "perpetual_order_depth": {"transport": "rest", "path": "/api/futures/orderbook/ask-bids-history"},
    "spot_large_trades": {"transport": "websocket", "channel_template": "spot_trades@{exchange}_{symbol}@{min_volume_usd}"},
    "perpetual_large_trades": {"transport": "websocket", "channel_template": "futures_trades@{exchange}_{symbol}@{min_volume_usd}"},
    "whale_index": {"transport": "rest", "path": "/api/futures/whale-index/history"},
    "market_data_history": {"transport": "rest", "path": "/api/coin/market-data-history"},
}

RawFetcher = Callable[..., Any]


def _request_id(request: Mapping[str, Any]) -> str:
    identity = {key: request.get(key) for key in ("provider", "transport", "endpoint_id", "path", "channel", "params", "dimensions")}
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:24]


def _request(endpoint_id: str, *, params: Mapping[str, Any], dimensions: Mapping[str, Any],
             collection_started_at: int | None = None, collection_ended_at: int | None = None) -> dict[str, Any]:
    manifest = ENDPOINT_MANIFEST[endpoint_id]
    request = {"provider": PROVIDER, "transport": manifest["transport"], "endpoint_id": endpoint_id,
               "path": manifest.get("path"), "channel": None, "params": dict(params), "dimensions": dict(dimensions)}
    if manifest["transport"] == "websocket":
        request["channel"] = manifest["channel_template"].format(exchange=dimensions["exchange"], symbol=dimensions["symbol"],
                                                                  min_volume_usd=params["min_volume_usd"])
        request["collection_started_at"] = collection_started_at
        request["collection_ended_at"] = collection_ended_at
    request["request_id"] = _request_id(request)
    return request


def build_liquidity_microstructure_fetch_plan(*, mode: str = "bootstrap", reference_timestamp: int | None = None,
                                               asset: str = "BTC", exchange: str = "Binance", spot_symbol: str = "BTCUSDT",
                                               perpetual_symbol: str = "BTCUSDT", timeframes: Sequence[str] = TIMEFRAMES,
                                               depth_ranges_percent: Sequence[int] = DEPTH_RANGES_PERCENT,
                                               large_trade_min_volume_usd: int = 10_000, history_limit: int = 100,
                                               overlap_seconds: int = 300,
                                               recovery_requests: Sequence[str | Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    if mode not in VALID_MODES:
        raise ValueError("invalid_liquidity_microstructure_mode")
    reference = int(reference_timestamp or time.time())
    start = reference - (overlap_seconds if mode == "incremental" else 86_400)
    common = {"asset": asset, "exchange": exchange}
    plan: list[dict[str, Any]] = []
    for market_type, symbol, heatmap_id, depth_id in (
        ("spot", spot_symbol, "spot_orderbook_heatmap", "spot_order_depth"),
        ("perpetual", perpetual_symbol, "perpetual_orderbook_heatmap", "perpetual_order_depth"),
    ):
        for timeframe in timeframes:
            dimensions = {**common, "market_type": market_type, "symbol": symbol, "timeframe": timeframe, "range_percent": None}
            params = {"exchange": exchange, "symbol": symbol, "interval": timeframe, "limit": history_limit,
                      "start_time": start * 1000, "end_time": reference * 1000}
            plan.append(_request(heatmap_id, params=params, dimensions=dimensions))
            for range_percent in depth_ranges_percent:
                depth_dimensions = {**dimensions, "range_percent": int(range_percent)}
                plan.append(_request(depth_id, params={**params, "range": int(range_percent)}, dimensions=depth_dimensions))
    for market_type, symbol, endpoint_id in (("spot", spot_symbol, "spot_large_trades"),
                                              ("perpetual", perpetual_symbol, "perpetual_large_trades")):
        dimensions = {**common, "market_type": market_type, "symbol": symbol, "timeframe": None, "range_percent": None}
        plan.append(_request(endpoint_id, params={"min_volume_usd": large_trade_min_volume_usd}, dimensions=dimensions,
                             collection_started_at=start, collection_ended_at=reference))
    for timeframe in timeframes:
        dimensions = {**common, "market_type": "perpetual", "symbol": perpetual_symbol, "timeframe": timeframe, "range_percent": None}
        params = {"exchange": exchange, "symbol": perpetual_symbol, "interval": timeframe, "limit": history_limit,
                  "start_time": start * 1000, "end_time": reference * 1000}
        plan.append(_request("whale_index", params=params, dimensions=dimensions))
    dimensions = {"asset": asset, "exchange": exchange, "market_type": None, "symbol": asset, "timeframe": "1d", "range_percent": None}
    plan.append(_request("market_data_history", params={"symbol": asset}, dimensions=dimensions))
    if mode != "recovery":
        return plan
    requested = list(recovery_requests or [])
    if not requested:
        raise ValueError("recovery_requests_required")
    selected = []
    for request in plan:
        for target in requested:
            if isinstance(target, str) and target in {request["request_id"], request["endpoint_id"]}:
                selected.append(request)
                break
            if isinstance(target, Mapping) and all(request.get("dimensions", {}).get(key) == value for key, value in target.items()):
                selected.append(request)
                break
    return selected


def execute_liquidity_microstructure_raw_request(request: Mapping[str, Any], fetcher: RawFetcher) -> dict[str, Any]:
    result = {**deepcopy(dict(request)), "status": "ok", "response": None, "error": None, "warnings": []}
    try:
        response = fetcher(**deepcopy(dict(request)))
        result["response"] = response
    except Exception as exc:
        result["status"] = "error"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
    return result


def extract_liquidity_microstructure_raw(*, fetcher: RawFetcher, mode: str = "bootstrap", **plan_arguments: Any) -> dict[str, Any]:
    plan = build_liquidity_microstructure_fetch_plan(mode=mode, **plan_arguments)
    return {"family": LIQUIDITY_MICROSTRUCTURE_FAMILY, "stage": "raw_extract", "mode": mode,
            "requests": [execute_liquidity_microstructure_raw_request(request, fetcher) for request in plan]}


class LiquidityMicrostructureRawExtractor:
    def __init__(self, fetcher: RawFetcher) -> None:
        self.fetcher = fetcher

    def build_plan(self, **kwargs: Any) -> list[dict[str, Any]]:
        return build_liquidity_microstructure_fetch_plan(**kwargs)

    def extract(self, **kwargs: Any) -> dict[str, Any]:
        return extract_liquidity_microstructure_raw(fetcher=self.fetcher, **kwargs)
