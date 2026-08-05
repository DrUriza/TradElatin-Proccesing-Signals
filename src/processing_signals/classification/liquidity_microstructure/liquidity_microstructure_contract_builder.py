"""Screen-contract assembler for Liquidity Microstructure v0.1."""

# ruff: noqa: E702, E731

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
import json
import math
from typing import Any

FAMILY = SCREEN_ID = "liquidity_microstructure"
SCREEN_SCHEMA = "trad_elatin.liquidity_microstructure.screen.v1"
SCREEN_VERSION = "1.0.0"
SCREEN_ROUTE = "/liquidity"
SCREEN_TITLE = "LIQUIDITY MICROSTRUCTURE"
SCREEN_SUBTITLE = "Order-book depth, large trades, whale activity & market context"
STAGE = "screen_contract"
MARKETS = ("spot", "perpetual")
TIMEFRAMES = ("1m", "5m", "15m", "1h")
DEFAULT_MARKET = "perpetual"
DEFAULT_TIMEFRAME = "1m"
DISPLAY_DEPTH_BASIS = "base_quantity"
REFERENCE_DEPTH_RANGE_PERCENT = 10
DISPLAY_POINT_LIMIT = 220
ORDERBOOK_TABLE_LIMIT = 12
LARGE_TRADE_TABLE_LIMIT = 50
KPI_IDS = ("bid_depth", "ask_depth", "spread", "liquidity_imbalance", "mid_price", "impact_1_btc")
CHART_IDS = ("order_depth_aggregated", "order_depth_zero_to_one", "order_depth_one_to_five", "large_trades_flow", "whale_activity", "market_history")
TABLE_IDS = ("orderbook_snapshot_aggregated", "orderbook_snapshot_zero_to_one", "orderbook_snapshot_one_to_five", "large_trades")
WIDGET_IDS = ("observed_liquidity", "large_trade_pressure", "whale_activity_state", "market_context", "spot_perpetual_comparison", "source_status")
DRILLDOWN_IDS = ("orderbook_details", "market_impact_details", "large_trades_details", "whale_activity_details", "market_history_details", "cross_market_details")
LIMITATIONS = ("coinglass_only", "no_glassnode", "no_cryptoquant", "large_trade_collection_may_be_incomplete", "whale_index_is_proprietary",
               "range_10_is_not_full_book", "observed_conditions_not_global_absolute_liquidity", "provider_is_coinglass_exchange_is_binance")


def _number(value: Any, *, positive: bool = False, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("invalid_numeric_argument")


def _iso(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("invalid_runtime_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("runtime_timestamp_timezone_required")


def _validate_runtime(runtime: Mapping[str, Any]) -> None:
    if not isinstance(runtime, Mapping):
        raise ValueError("runtime_context_must_be_mapping")
    required = {"data_mode", "is_demo", "generated_at", "updated_at", "connection_status", "cache_status", "latency_ms",
                "refresh_interval_seconds", "cache_ttl_seconds"}
    if not required.issubset(runtime):
        raise ValueError("runtime_context_missing_fields")
    if runtime["data_mode"] not in {"live", "synthetic"} or not isinstance(runtime["is_demo"], bool):
        raise ValueError("invalid_runtime_mode")
    if (runtime["data_mode"] == "synthetic") != runtime["is_demo"]:
        raise ValueError("runtime_mode_demo_mismatch")
    if runtime["connection_status"] not in {"connected", "degraded", "disconnected", "not_reported"}:
        raise ValueError("invalid_connection_status")
    if runtime["cache_status"] not in {"hit", "miss", "stale", "not_reported"}:
        raise ValueError("invalid_cache_status")
    _iso(runtime["generated_at"]); _iso(runtime["updated_at"])
    _number(runtime["latency_ms"], nullable=True)
    if runtime["latency_ms"] is not None and runtime["latency_ms"] < 0:
        raise ValueError("invalid_latency")
    _number(runtime["refresh_interval_seconds"], positive=True, nullable=True)
    _number(runtime["cache_ttl_seconds"], positive=True, nullable=True)


def _validate_json(value: Any) -> None:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("non_string_json_key")
        for item in value.values():
            _validate_json(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _validate_json(item)
    elif isinstance(value, float) and (not math.isfinite(value) or (value == 0 and math.copysign(1, value) < 0)):
        raise ValueError("invalid_json_number")


def validate_liquidity_microstructure_builder_inputs(bundle: Mapping[str, Any], *, runtime_context: Mapping[str, Any],
                                                      selected_market: str = DEFAULT_MARKET, selected_timeframe: str = DEFAULT_TIMEFRAME,
                                                      display_point_limit: int = DISPLAY_POINT_LIMIT, orderbook_table_limit: int = ORDERBOOK_TABLE_LIMIT,
                                                      large_trade_table_limit: int = LARGE_TRADE_TABLE_LIMIT) -> None:
    if not isinstance(bundle, Mapping) or not isinstance(bundle.get("processing"), Mapping) or not isinstance(bundle.get("classification"), Mapping):
        raise ValueError("invalid_builder_bundle")
    if selected_market not in MARKETS or selected_timeframe not in TIMEFRAMES:
        raise ValueError("invalid_selector")
    for limit in (display_point_limit, orderbook_table_limit, large_trade_table_limit):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("invalid_display_limit")
    _validate_runtime(runtime_context)
    p, c = bundle["processing"], bundle["classification"]
    if p.get("family") != FAMILY or p.get("stage") != "processing" or p.get("configuration", {}).get("version") != "0.1":
        raise ValueError("invalid_processing_contract")
    if c.get("family") != FAMILY or c.get("stage") != "classification" or c.get("classification_version") != "0.1" or c.get("classification_rule_version") != "liquidity_microstructure.rules.v0.1":
        raise ValueError("invalid_classification_contract")
    pairs = ((p.get("mode"), c.get("mode")), (p.get("reference_timestamp"), c.get("reference_timestamp")),
             (p.get("execution_timestamp"), c.get("source_execution_timestamp")), (p.get("context"), c.get("context")))
    if any(left != right for left, right in pairs):
        raise ValueError("upstream_contract_mismatch")
    for source in (p, c):
        if set(source.get("markets", {})) != set(MARKETS):
            raise ValueError("upstream_contract_mismatch")
    for key in ("data_mode", "is_demo"):
        if key in p.get("context", {}) and p["context"][key] != runtime_context[key]:
            raise ValueError("upstream_contract_mismatch")
    _validate_json(bundle); _validate_json(runtime_context)


def _component(component_id: str, title: str, status: str, source_paths: list[str], **extra: Any) -> dict[str, Any]:
    result = {"status": status, "reason": None if status == "available" else "source_not_available", "source_paths": source_paths,
              "warnings": [], "errors": []}
    result.update(extra)
    result[next(key for key in ("chart_id", "table_id", "widget_id", "drilldown_id") if key in extra)] = component_id
    result["title"] = title
    return result


def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return "--"
    return {"btc": f"{value:,.2f} BTC", "bps": f"{value:,.1f} bps", "percent": f"{value:+.1f}%", "usd": f"${value:,.2f}"}[kind]


def _kpi(metric_id: str, label: str, value: Any, unit: str, kind: str, status: str, source_paths: list[str], timestamp: Any,
         color: str = "neutral", metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    usable = status in {"available", "partial"} and value is not None
    return {"metric_id": metric_id, "label": label, "value": value if usable else None, "display_value": _fmt(value, kind) if usable else "--", "unit": unit,
            "status": status, "reason": None if usable else "source_not_available", "color_token": color, "source_paths": source_paths,
            "source_timestamp": timestamp, "metadata": deepcopy(dict(metadata or {}))}


def _depth_chart(chart_id: str, title: str, current: Mapping[str, Any], limit: int, band: tuple[float, float] | None, path: str) -> dict[str, Any]:
    def selected(side: str) -> tuple[list[dict[str, Any]], int]:
        values = list(current.get(f"{side}_levels", []))
        if band is not None:
            low, high = band
            values = [row for row in values if (row.get("distance_percent") is not None and low < row["distance_percent"] <= high)]
        return deepcopy(values[:limit]), len(values)
    bids, bid_count = selected("bid"); asks, ask_count = selected("ask")
    records = [{"side": "bid", **row} for row in bids] + [{"side": "ask", **row} for row in asks]
    status = current.get("status", "unavailable")
    return _component(chart_id, title, status, [path], chart_id=chart_id, chart_type="mirrored_cumulative_depth",
                      selector_behavior="selected_market_and_timeframe", data_as_of=current.get("timestamp"), series=["Bids", "Asks"], records=records,
                      metadata={"scope": "single_exchange_visible_orderbook", "provider": "coinglass", "exchange": "Binance", "not_full_market_book": True,
                                "x_axis": {"rendering": "mirrored_by_side", "field": "distance_percent"}, "basis": "cumulative_quantity_base", "unit": "BTC",
                                "bid_levels_available": bid_count, "bid_levels_returned": len(bids), "ask_levels_available": ask_count,
                                "ask_levels_returned": len(asks), "display_point_limit": limit, "depth_truncated": bid_count > limit or ask_count > limit,
                                "cumulative_origin": "mid_price", "band_filter": None if band is None else {"min_exclusive": band[0], "max_inclusive": band[1]}})


def _table(table_id: str, title: str, chart: Mapping[str, Any], summary: Mapping[str, Any], limit: int, path: str) -> dict[str, Any]:
    bids = [deepcopy(row) for row in chart["records"] if row["side"] == "bid"][:limit]
    asks = [deepcopy(row) for row in chart["records"] if row["side"] == "ask"][:limit]
    available = {"bid": sum(row["side"] == "bid" for row in chart["records"]), "ask": sum(row["side"] == "ask" for row in chart["records"])}
    return _component(table_id, title, chart["status"], [path], table_id=table_id,
                      columns=["price", "quantity_base", "cumulative_quantity_base", "notional_quote", "distance_percent"], bids=bids, asks=asks,
                      summary=deepcopy(summary), metadata={"rows_available": available, "rows_returned": {"bid": len(bids), "ask": len(asks)},
                                                          "rows_truncated": available["bid"] > limit or available["ask"] > limit, "display_limit": limit})


def _fallback(mode: str | None, runtime: Mapping[str, Any] | None, error: str) -> dict[str, Any]:
    invalid = lambda key, title: {key: title, "title": title, "status": "invalid", "reason": "invalid_upstream_contract", "source_paths": [], "warnings": [], "errors": [error]}
    return {"schema": {"id": SCREEN_SCHEMA, "version": SCREEN_VERSION}, "screen": {"id": SCREEN_ID, "family": FAMILY, "route": SCREEN_ROUTE, "title": SCREEN_TITLE, "subtitle": SCREEN_SUBTITLE},
            "stage": STAGE, "mode": mode if mode in {"bootstrap", "incremental", "recovery"} else "bootstrap", "context": {}, "badges": [],
            "selectors": {"market": {}, "timeframe": {}}, "operational_status": {"status": "invalid", "reason": "invalid_upstream_contract"},
            "kpis": {"items": [_kpi(key, key.replace("_", " ").title(), None, "", "bps", "invalid", [], None) for key in KPI_IDS]},
            "charts": {key: invalid("chart_id", key) | {"chart_id": key, "series": [], "records": []} for key in CHART_IDS},
            "tables": {key: invalid("table_id", key) | {"table_id": key, "columns": [], "bids": [], "asks": [], "rows": [], "summary": {}} for key in TABLE_IDS},
            "widgets": {key: invalid("widget_id", key) | {"widget_id": key, "current": None, "items": []} for key in WIDGET_IDS},
            "drilldowns": {key: invalid("drilldown_id", key) | {"drilldown_id": key, "enabled": False, "current": None, "details": {}} for key in DRILLDOWN_IDS},
            "availability": {"required": {}, "optional": {}, "summary": {"required_available": 0, "required_total": 22, "optional_available": 0, "optional_total": 7}},
            "quality": {"status": "invalid", "contract_complete": True, "data_complete": False, "processing_status": "invalid", "classification_status": "invalid",
                        "availability": {}, "missing_required_components": list(KPI_IDS + CHART_IDS + TABLE_IDS + WIDGET_IDS), "partial_components": [],
                        "unavailable_components": [], "invalid_components": list(KPI_IDS + CHART_IDS + TABLE_IDS + WIDGET_IDS), "warnings": [], "errors": [error], "data_as_of": None}}


def build_liquidity_microstructure_screen_contract(bundle: Mapping[str, Any], *, runtime_context: Mapping[str, Any], selected_market: str = DEFAULT_MARKET,
                                                    selected_timeframe: str = DEFAULT_TIMEFRAME, display_point_limit: int = DISPLAY_POINT_LIMIT,
                                                    orderbook_table_limit: int = ORDERBOOK_TABLE_LIMIT,
                                                    large_trade_table_limit: int = LARGE_TRADE_TABLE_LIMIT) -> dict[str, Any]:
    validate_liquidity_microstructure_builder_inputs(bundle, runtime_context=runtime_context, selected_market=selected_market,
                                                      selected_timeframe=selected_timeframe, display_point_limit=display_point_limit,
                                                      orderbook_table_limit=orderbook_table_limit, large_trade_table_limit=large_trade_table_limit)
    p, c, runtime = deepcopy(bundle["processing"]), deepcopy(bundle["classification"]), deepcopy(runtime_context)
    market_path = f"markets.{selected_market}"; ob_path = f"{market_path}.orderbook.timeframes.{selected_timeframe}"
    depth_path = f"{market_path}.order_depth.timeframes.{selected_timeframe}"
    ob, cob = p["markets"][selected_market]["orderbook"]["timeframes"][selected_timeframe], c["markets"][selected_market]["orderbook"]["timeframes"][selected_timeframe]
    current = ob.get("current") or {}; depth = p["markets"][selected_market]["order_depth"]["timeframes"][selected_timeframe]
    reference = next((row for row in reversed(depth.get("direct_ranges", [])) if row.get("range_percent") == REFERENCE_DEPTH_RANGE_PERCENT and row.get("status") in {"available", "partial"}), None)
    base = (reference or {}).get(DISPLAY_DEPTH_BASIS, {}); timestamp = (reference or {}).get("timestamp")
    depth_class = c["markets"][selected_market]["order_depth"]["timeframes"][selected_timeframe].get("classification", {}).get("reference_balance") or {}
    ob_class = cob.get("classification", {}); impact = current.get("market_impact", {}); worst = impact.get("worst_side_impact_bps")
    filled = bool(impact.get("buy", {}).get("fully_filled")) and bool(impact.get("sell", {}).get("fully_filled"))
    kpis = [_kpi("bid_depth", "Bid Depth", base.get("bid"), "BTC", "btc", base.get("status", "unavailable"), [f"{depth_path}.direct_ranges[range_percent=10].base_quantity.bid"], timestamp, depth_class.get("display_color_token", "neutral")),
            _kpi("ask_depth", "Ask Depth", base.get("ask"), "BTC", "btc", base.get("status", "unavailable"), [f"{depth_path}.direct_ranges[range_percent=10].base_quantity.ask"], timestamp, depth_class.get("display_color_token", "neutral")),
            _kpi("spread", "Spread", current.get("spread_bps"), "bps", "bps", current.get("status", "unavailable"), [f"{ob_path}.current.spread_bps"], current.get("timestamp"), ob_class.get("spread_condition", {}).get("display_color_token", "neutral"), current),
            _kpi("liquidity_imbalance", "Liquidity Imbalance", base.get("imbalance_percent"), "%", "percent", base.get("status", "unavailable"), [f"{depth_path}.direct_ranges[range_percent=10].base_quantity.imbalance_percent"], timestamp, depth_class.get("display_color_token", "neutral"), base | {"basis": DISPLAY_DEPTH_BASIS, "range_percent": 10}),
            _kpi("mid_price", "Mid Price", current.get("mid_price"), "USD", "usd", current.get("status", "unavailable"), [f"{ob_path}.current.mid_price"], current.get("timestamp"), metadata={"best_bid": current.get("best_bid"), "best_ask": current.get("best_ask")}),
            _kpi("impact_1_btc", "Impact 1 BTC", worst if filled else None, "bps", "bps", impact.get("status", "unavailable") if filled else "partial", [f"{ob_path}.current.market_impact.worst_side_impact_bps"], current.get("timestamp"), ob_class.get("market_impact", {}).get("worst_side", {}).get("display_color_token", "neutral"), impact)]
    charts = {"order_depth_aggregated": _depth_chart("order_depth_aggregated", "ORDER DEPTH (AGGREGATED)", current, display_point_limit, None, ob_path),
              "order_depth_zero_to_one": _depth_chart("order_depth_zero_to_one", "ORDER DEPTH (0–1%)", current, display_point_limit, (-1e-15, 1), ob_path),
              "order_depth_one_to_five": _depth_chart("order_depth_one_to_five", "ORDER DEPTH (1–5%)", current, display_point_limit, (1, 5), ob_path)}
    bands = current.get("bands", {})
    tables = {"orderbook_snapshot_aggregated": _table("orderbook_snapshot_aggregated", "ORDER BOOK SNAPSHOT (AGGREGATED)", charts["order_depth_aggregated"], bands.get("full_visible_book", {}), orderbook_table_limit, ob_path),
              "orderbook_snapshot_zero_to_one": _table("orderbook_snapshot_zero_to_one", "ORDER BOOK SNAPSHOT (0–1%)", charts["order_depth_zero_to_one"], bands.get("zero_to_one", {}), orderbook_table_limit, ob_path),
              "orderbook_snapshot_one_to_five": _table("orderbook_snapshot_one_to_five", "ORDER BOOK SNAPSHOT (1–5%)", charts["order_depth_one_to_five"], bands.get("one_to_five", {}), orderbook_table_limit, ob_path)}
    trades = p["markets"][selected_market]["large_trades"]; c_trades = c["markets"][selected_market]["large_trades"]
    windows = [{"window": window, **deepcopy(row), "status": trades["status"], "reason": trades.get("reason")} for window, row in trades.get("windows", {}).items()]
    charts["large_trades_flow"] = _component("large_trades_flow", "LARGE TRADES", trades["status"], [f"{market_path}.large_trades.windows"], chart_id="large_trades_flow", chart_type="overlapping_window_flow", selector_behavior="selected_market_and_timeframe", data_as_of=trades.get("coverage", {}).get("observed_last_timestamp"), series=["buy_volume_usd", "sell_volume_usd", "net_flow_usd"], items=windows, metadata={"window_semantics": "overlapping_lookback_windows", "selected_window": selected_timeframe, **deepcopy(trades.get("coverage", {}))})
    events = sorted((deepcopy(row) for row in trades.get("large_trade_events", []) if row.get("meets_configured_threshold") is True), key=lambda row: row["timestamp"], reverse=True)
    tables["large_trades"] = _component("large_trades", "LARGE TRADES — RECENT EVENTS", trades["status"], [f"{market_path}.large_trades.large_trade_events"], table_id="large_trades", columns=list(events[0]) if events else [], rows=events[:large_trade_table_limit], bids=[], asks=[], summary={}, metadata={"events_available": len(events), "events_returned": min(len(events), large_trade_table_limit), "events_truncated": len(events) > large_trade_table_limit, **deepcopy(trades.get("coverage", {}))})
    whale, c_whale = p["whale_activity"]["timeframes"][selected_timeframe], c["whale_activity"]["timeframes"][selected_timeframe]
    whale_records = deepcopy(whale.get("records", [])[-display_point_limit:])
    charts["whale_activity"] = _component("whale_activity", "WHALE ACTIVITY", whale["status"], [f"whale_activity.timeframes.{selected_timeframe}"], chart_id="whale_activity", chart_type="line", selector_behavior="fixed_perpetual_market_selected_timeframe", data_as_of=(whale.get("current") or {}).get("timestamp"), series=["whale_index_value"], records=whale_records, metadata={"scope": "perpetual", "statistics": deepcopy(whale.get("statistics", {})), "indicator": "provider_proprietary"})
    history = p["market_history"]; history_records = deepcopy(history.get("records", [])[-display_point_limit:])
    charts["market_history"] = _component("market_history", "MARKET HISTORY", history["status"], ["market_history.records"], chart_id="market_history", chart_type="multi_series_line", selector_behavior="fixed_asset_daily_context", data_as_of=(history.get("current") or {}).get("timestamp"), series=["price", "market_cap", "circulating_supply"], records=history_records, metadata={"scope": "asset_level_daily", "changes": deepcopy(history.get("changes", {}))})
    trade_atom = c_trades.get("classification", {}).get(selected_timeframe, {}); whale_atom = c_whale.get("classification", {})
    widgets = {"observed_liquidity": _component("observed_liquidity", "OBSERVED LIQUIDITY CONDITIONS", c["quality"]["status"] if c["quality"]["status"] != "ok" else "available", ["summary.observed_liquidity"], widget_id="observed_liquidity", current=deepcopy(c["markets"][selected_market]["summary"][selected_timeframe]), items=[], data_as_of=current.get("timestamp"), scope="observed_not_global_absolute_liquidity"),
               "large_trade_pressure": _component("large_trade_pressure", "LARGE TRADE PRESSURE", trade_atom.get("status", "unavailable"), [f"markets.{selected_market}.large_trades.classification.{selected_timeframe}"], widget_id="large_trade_pressure", current=deepcopy(trade_atom), items=[], data_as_of=trade_atom.get("source_timestamp")),
               "whale_activity_state": _component("whale_activity_state", "WHALE ACTIVITY STATE", whale_atom.get("status", "unavailable"), [f"whale_activity.timeframes.{selected_timeframe}.classification"], widget_id="whale_activity_state", current=deepcopy(whale_atom) | {"rolling_z_score_20": whale.get("statistics", {}).get("rolling_z_score_20"), "scope": "perpetual"}, items=[], data_as_of=(whale.get("current") or {}).get("timestamp")),
               "market_context": _component("market_context", "MARKET CONTEXT", history["status"], ["market_history", "classification.market_history"], widget_id="market_context", current=deepcopy(history.get("current")), items=[deepcopy(row) for row in c["market_history"].get("changes", {}).values()], data_as_of=(history.get("current") or {}).get("timestamp")),
               "spot_perpetual_comparison": _component("spot_perpetual_comparison", "SPOT / PERPETUAL COMPARISON", c["comparison"]["spot_perpetual"].get("status", "unavailable"), ["comparison.spot_perpetual"], widget_id="spot_perpetual_comparison", current=deepcopy(c["comparison"]["spot_perpetual"]), items=[], data_as_of=current.get("timestamp")),
               "source_status": _component("source_status", "SOURCE STATUS", "available", ["quality", "runtime_context"], widget_id="source_status", current=None, data_as_of=max(filter(lambda value: isinstance(value, int), [current.get("timestamp"), timestamp, (history.get("current") or {}).get("timestamp")]), default=None), items=[{"provider_id": "coinglass", "label": "CoinGlass", "exchange": "Binance", "status": runtime["connection_status"]}, {"provider_id": "internal_processing", "label": "Internal Processing", "status": p["quality"]["status"]}, {"provider_id": "internal_classification", "label": "Internal Classification", "status": c["quality"]["status"]}])}
    data_as_of = widgets["source_status"]["data_as_of"]
    drilldowns = {"orderbook_details": deepcopy(current), "market_impact_details": deepcopy(impact), "large_trades_details": deepcopy(trades),
                  "whale_activity_details": deepcopy(whale), "market_history_details": deepcopy(history), "cross_market_details": deepcopy(c["comparison"]["spot_perpetual"])}
    drilldowns = {key: _component(key, key.replace("_", " ").upper(), value.get("status", "available"), [key], drilldown_id=key, enabled=True, current=value.get("current"), details=value) for key, value in drilldowns.items()}
    required_components = {**{f"kpis.{row['metric_id']}": row for row in kpis}, **{f"charts.{key}": value for key, value in charts.items()},
                           **{f"tables.{key}": value for key, value in tables.items()}, **{f"widgets.{key}": value for key, value in widgets.items() if key != "spot_perpetual_comparison"}}
    optional_components = {"widgets.spot_perpetual_comparison": widgets["spot_perpetual_comparison"], **{f"drilldowns.{key}": value for key, value in drilldowns.items()}}
    entry = lambda value: {"status": value["status"], "reason": value.get("reason"), "source_paths": deepcopy(value.get("source_paths", []))}
    availability = {"required": {key: entry(value) for key, value in required_components.items()}, "optional": {key: entry(value) for key, value in optional_components.items()}}
    availability["summary"] = {"required_available": sum(value["status"] == "available" for value in required_components.values()), "required_total": len(required_components),
                               "optional_available": sum(value["status"] == "available" for value in optional_components.values()), "optional_total": len(optional_components)}
    statuses = {key: value["status"] for key, value in required_components.items()}; invalid = sorted(key for key, value in statuses.items() if value == "invalid")
    partial = sorted(key for key, value in statuses.items() if value == "partial"); unavailable = sorted(key for key, value in statuses.items() if value == "unavailable")
    quality_status = "invalid" if invalid or p["quality"]["status"] == "invalid" or c["quality"]["status"] == "invalid" else "partial" if partial or unavailable else "ok"
    badges = ([{"id": "DEMO", "color_token": "warning"}] if runtime["is_demo"] else []) + ([{"id": "DEGRADED", "color_token": "warning"}] if quality_status == "partial" or runtime["connection_status"] == "degraded" else []) + ([{"id": "STALE", "color_token": "warning"}] if runtime["cache_status"] == "stale" else [])
    output = {"schema": {"id": SCREEN_SCHEMA, "version": SCREEN_VERSION}, "screen": {"id": SCREEN_ID, "family": FAMILY, "route": SCREEN_ROUTE, "title": SCREEN_TITLE, "subtitle": SCREEN_SUBTITLE}, "stage": STAGE, "mode": p["mode"],
              "context": {"asset": p["context"].get("asset"), "base_asset": "BTC", "quote_asset": "USDT", "spot_symbol": p["markets"]["spot"]["orderbook"]["timeframes"][selected_timeframe].get("current", {}).get("symbol"), "perpetual_symbol": p["markets"]["perpetual"]["orderbook"]["timeframes"][selected_timeframe].get("current", {}).get("symbol"), "selected_symbol": current.get("symbol"), "selected_market": selected_market, "selected_timeframe": selected_timeframe, "provider": {"id": "coinglass", "label": "CoinGlass"}, "exchange": "Binance", "reference_timestamp": p["reference_timestamp"], "processing_execution_timestamp": p["execution_timestamp"], "classification_execution_timestamp": c["execution_timestamp"], "data_as_of": data_as_of, **runtime, "display_depth_basis": DISPLAY_DEPTH_BASIS, "reference_depth_range_percent": 10, "market_impact_quantity_base": p["configuration"]["market_impact_quantity_base"], "calibration_status": c["configuration"]["calibration_status"], "calculation_history": "upstream_preserved", "presentation_policy": "select_filter_truncate_without_recalculation", "units": {"depth": "BTC", "spread": "bps", "impact": "bps"}, "limitations": list(LIMITATIONS)},
              "badges": badges, "selectors": {"market": {"selector_id": "liquidity_market", "selected": selected_market, "options": list(MARKETS), "behavior": "contract_rebuild_required"}, "timeframe": {"selector_id": "liquidity_timeframe", "selected": selected_timeframe, "options": list(TIMEFRAMES), "behavior": "contract_rebuild_required"}},
              "operational_status": {"status": "invalid" if quality_status == "invalid" else "partial" if quality_status == "partial" or runtime["connection_status"] in {"degraded", "disconnected"} else "available", "provider": "coinglass", "exchange": "Binance", **runtime, "data_as_of": data_as_of, "quality_status": quality_status, "reason": None},
              "kpis": {"items": kpis}, "charts": charts, "tables": tables, "widgets": widgets, "drilldowns": drilldowns, "availability": availability,
              "quality": {"status": quality_status, "contract_complete": True, "data_complete": not partial and not unavailable, "processing_status": p["quality"]["status"], "classification_status": c["quality"]["status"], "availability": deepcopy(availability["summary"]), "missing_required_components": unavailable, "partial_components": partial, "unavailable_components": unavailable, "invalid_components": invalid, "warnings": [], "errors": [], "data_as_of": data_as_of}}
    _validate_json(output); json.dumps(output, ensure_ascii=False, allow_nan=False)
    return output


class LiquidityMicrostructureContractBuilder:
    def __init__(self, *, selected_market: str = DEFAULT_MARKET, selected_timeframe: str = DEFAULT_TIMEFRAME,
                 display_point_limit: int = DISPLAY_POINT_LIMIT, orderbook_table_limit: int = ORDERBOOK_TABLE_LIMIT,
                 large_trade_table_limit: int = LARGE_TRADE_TABLE_LIMIT) -> None:
        if selected_market not in MARKETS or selected_timeframe not in TIMEFRAMES or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (display_point_limit, orderbook_table_limit, large_trade_table_limit)):
            raise ValueError("invalid_builder_arguments")
        self.arguments = {"selected_market": selected_market, "selected_timeframe": selected_timeframe, "display_point_limit": display_point_limit,
                          "orderbook_table_limit": orderbook_table_limit, "large_trade_table_limit": large_trade_table_limit}

    def run(self, bundle: Mapping[str, Any], *, runtime_context: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return build_liquidity_microstructure_screen_contract(bundle, runtime_context=runtime_context, **self.arguments)
        except ValueError as exc:
            mode = bundle.get("processing", {}).get("mode") if isinstance(bundle, Mapping) else None
            return _fallback(mode, runtime_context if isinstance(runtime_context, Mapping) else None, str(exc))
