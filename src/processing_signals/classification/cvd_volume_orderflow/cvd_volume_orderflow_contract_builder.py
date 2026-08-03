"""Pure visual contract builder for CVD volume/order-flow v0.1."""
from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

FAMILY = "cvd_volume_orderflow"
PROCESSING_VERSION = "0.1.0"
CLASSIFICATION_VERSION = "0.1.0"
SCREEN_SCHEMA = "trad_elatin.cvd_volume_orderflow.screen.v1"
SCREEN_VERSION = "1.0.0"
SCREEN_ID = "cvd_volume_orderflow"
SCREEN_ROUTE = "/cvd-orderflow"
SCREEN_TITLE = "CVD & ORDER FLOW"
SCREEN_SUBTITLE = "Cumulative volume delta, trades & market microstructure"
MARKETS = ("general", "spot", "futures")
TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
DEFAULT_MARKET = "general"
DEFAULT_TIMEFRAME = "15m"
DISPLAY_POINT_LIMIT = 220
VALID_SOURCE_STATUS = {"available", "partial", "unavailable", "invalid"}
VALID_QUALITY_STATUS = {"ok", "partial", "invalid"}
_PRIORITY = {"available": 0, "partial": 1, "unavailable": 2, "invalid": 3}


def _sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _finite_tree(value: Any, path: str = "bundle") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non_finite_value:{path}")
    if isinstance(value, Mapping):
        for key, child in value.items():
            _finite_tree(child, f"{path}.{key}")
    elif _sequence(value):
        for index, child in enumerate(value):
            _finite_tree(child, f"{path}[{index}]")


def _number(value: Any, path: str, *, nullable: bool = True) -> Any:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"invalid_numeric_value:{path}")
    if value == 0:
        return 0.0 if isinstance(value, float) else 0
    return value


def _timestamp(value: Any, path: str, *, nullable: bool = True) -> Any:
    if value is None and nullable:
        return None
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid_timestamp:{path}")
    return value


def _status(value: Any, path: str) -> str:
    if value not in VALID_SOURCE_STATUS:
        raise ValueError(f"invalid_source_status:{path}")
    return value


def _reason(status: str, reason: Any, fallback: str = "source_value_unavailable") -> str | None:
    return None if status == "available" else (reason if isinstance(reason, str) and reason else fallback)


def _combine(statuses: Sequence[str]) -> str:
    if not statuses:
        return "unavailable"
    if all(value == "unavailable" for value in statuses):
        return "unavailable"
    if "invalid" in statuses:
        return "invalid"
    if any(value != "available" for value in statuses):
        return "partial"
    return "available"


def _availability(status: str, reason: str | None, paths: Sequence[str]) -> dict[str, Any]:
    return {"status": status, "reason": _reason(status, reason), "source_paths": list(paths)}


def _metric(source: Any, path: str) -> tuple[Any, str, str | None]:
    if not isinstance(source, Mapping):
        raise ValueError(f"invalid_metric:{path}")
    status = _status(source.get("status"), f"{path}.status")
    return _number(source.get("value"), f"{path}.value"), status, _reason(status, source.get("reason"))


def _classification(atom: Any) -> dict[str, Any] | None:
    if not isinstance(atom, Mapping):
        return None
    return {"state": copy.deepcopy(atom.get("state")), "direction": copy.deepcopy(atom.get("direction"))}


def _copy_classification(value: Any) -> Any:
    """Copy a Classification fragment and qualify its contract-relative paths."""
    if isinstance(value, Mapping):
        output = {}
        for key, child in value.items():
            if key in {"source_path", "source_paths"}:
                paths = [child] if key == "source_path" else child
                if not _sequence(paths):
                    raise ValueError("invalid_source_paths")
                qualified = []
                for path in paths:
                    if not isinstance(path, str):
                        raise ValueError("invalid_source_path")
                    if path.startswith(("processing.", "classification.")):
                        qualified.append(path)
                    elif path.startswith("markets."):
                        qualified.append(f"processing.{path}")
                    elif path.startswith("confirmations."):
                        qualified.append(f"classification.{path}")
                    else:
                        raise ValueError("invalid_source_path")
                output[key] = qualified[0] if key == "source_path" else qualified
            else:
                output[key] = _copy_classification(child)
        return output
    if _sequence(value):
        return [_copy_classification(child) for child in value]
    return copy.deepcopy(value)


def _validated_paths(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "source_path":
                paths = [child]
            elif key == "source_paths":
                if not _sequence(child):
                    raise ValueError("invalid_source_paths")
                paths = child
            else:
                paths = []
            for path in paths:
                if not isinstance(path, str) or not path.startswith(("processing.", "classification.")):
                    raise ValueError("invalid_source_path")
            _validated_paths(child)
    elif _sequence(value):
        for child in value:
            _validated_paths(child)


class CvdVolumeOrderflowContractBuilder:
    """Validate two frozen contracts and project them into a screen contract."""

    def __init__(self, *, selected_market: str = DEFAULT_MARKET, selected_timeframe: str = DEFAULT_TIMEFRAME,
                 display_point_limit: int = DISPLAY_POINT_LIMIT) -> None:
        if selected_market not in MARKETS:
            raise ValueError("invalid_selected_market")
        if selected_timeframe not in TIMEFRAMES:
            raise ValueError("invalid_selected_timeframe")
        if type(display_point_limit) is not int or not 0 < display_point_limit <= DISPLAY_POINT_LIMIT:
            raise ValueError("invalid_display_point_limit")
        self.selected_market = selected_market
        self.selected_timeframe = selected_timeframe
        self.display_point_limit = display_point_limit

    def validate_bundle(self, bundle: Any) -> None:
        if not isinstance(bundle, Mapping):
            raise ValueError("bundle_must_be_mapping")
        if set(bundle) != {"processing", "classification"}:
            raise ValueError("bundle_root_keys_mismatch")
        self.validate_processing_contract(bundle["processing"])
        self.validate_classification_contract(bundle["classification"])
        self.validate_bundle_consistency(bundle["processing"], bundle["classification"])
        _finite_tree(bundle)

    def validate_processing_contract(self, contract: Any) -> None:
        if not isinstance(contract, Mapping):
            raise ValueError("processing_contract_must_be_mapping")
        if contract.get("family") != FAMILY or contract.get("stage") != "processing" or contract.get("version") != PROCESSING_VERSION:
            raise ValueError("incompatible_processing_contract")
        if contract.get("mode") not in {"bootstrap", "incremental", "recovery"}:
            raise ValueError("invalid_processing_mode")
        context, parameters, markets, quality = (contract.get(key) for key in ("context", "parameters", "markets", "quality"))
        if not all(isinstance(value, Mapping) for value in (context, parameters, markets, quality)) or set(markets) != set(MARKETS):
            raise ValueError("invalid_processing_structure")
        if context.get("data_mode") == "synthetic" and context.get("is_demo") is not True:
            raise ValueError("synthetic_requires_demo")
        if context.get("data_mode") == "live" and context.get("is_demo") is not False:
            raise ValueError("live_cannot_be_demo")
        for key in ("reference_timestamp", "processing_timestamp"):
            _timestamp(context.get(key), f"processing.context.{key}", nullable=False)
        if quality.get("status") not in VALID_QUALITY_STATUS:
            raise ValueError("invalid_processing_quality")
        for market in MARKETS:
            payload = markets[market]
            if not isinstance(payload, Mapping) or not isinstance(payload.get("timeframes"), Mapping) or set(payload["timeframes"]) != set(TIMEFRAMES):
                raise ValueError("invalid_processing_timeframes")
            if not isinstance(payload.get("window_summaries"), Mapping) or set(payload["window_summaries"]) != {"1h", "24h"}:
                raise ValueError("invalid_processing_summaries")
            for timeframe in TIMEFRAMES:
                source = payload["timeframes"][timeframe]
                if not isinstance(source, Mapping) or not _sequence(source.get("records")):
                    raise ValueError("invalid_processing_timeframe")
                _status(source.get("status"), f"processing.{market}.{timeframe}")
                previous = None
                for row in source["records"]:
                    if not isinstance(row, Mapping):
                        raise ValueError("invalid_processing_record")
                    timestamp = _timestamp(row.get("timestamp"), "processing.record.timestamp", nullable=False)
                    if previous is not None and timestamp <= previous:
                        raise ValueError("records_not_strictly_ascending")
                    previous = timestamp
                if source.get("current") is not None and not isinstance(source["current"], Mapping):
                    raise ValueError("invalid_processing_current")
            for window in ("1h", "24h"):
                if not isinstance(payload["window_summaries"][window], Mapping):
                    raise ValueError("invalid_processing_summary")
                _status(payload["window_summaries"][window].get("status"), "processing.summary.status")

    def validate_classification_contract(self, contract: Any) -> None:
        if not isinstance(contract, Mapping):
            raise ValueError("classification_contract_must_be_mapping")
        if contract.get("family") != FAMILY or contract.get("stage") != "classification" or contract.get("version") != CLASSIFICATION_VERSION:
            raise ValueError("incompatible_classification_contract")
        if contract.get("mode") not in {"bootstrap", "incremental", "recovery"}:
            raise ValueError("invalid_classification_mode")
        context, parameters, classified, quality = (contract.get(key) for key in ("context", "parameters", "classifications", "quality"))
        if not all(isinstance(value, Mapping) for value in (context, parameters, classified, quality)):
            raise ValueError("invalid_classification_structure")
        markets = classified.get("markets")
        if not isinstance(markets, Mapping) or set(markets) != set(MARKETS):
            raise ValueError("invalid_classification_markets")
        if quality.get("status") not in VALID_QUALITY_STATUS:
            raise ValueError("invalid_classification_quality")
        _timestamp(context.get("classification_timestamp"), "classification.context.classification_timestamp", nullable=False)
        for market in MARKETS:
            payload = markets[market]
            if not isinstance(payload, Mapping) or not isinstance(payload.get("timeframes"), Mapping) or set(payload["timeframes"]) != set(TIMEFRAMES):
                raise ValueError("invalid_classification_timeframes")
            if not isinstance(payload.get("window_summaries"), Mapping) or set(payload["window_summaries"]) != {"1h", "24h"}:
                raise ValueError("invalid_classification_summaries")

    def validate_bundle_consistency(self, processing: Mapping[str, Any], classification: Mapping[str, Any]) -> None:
        if processing["mode"] != classification["mode"]:
            raise ValueError("bundle_mode_mismatch")
        p_context, c_context = processing["context"], classification["context"]
        for key in ("base_asset", "pair_symbol", "data_mode", "is_demo", "reference_timestamp", "processing_timestamp"):
            if p_context.get(key) != c_context.get(key):
                raise ValueError(f"bundle_context_mismatch:{key}")
        if tuple(c_context.get("markets", ())) != MARKETS or tuple(c_context.get("timeframes", ())) != TIMEFRAMES:
            raise ValueError("classification_context_scope_mismatch")

    def build_context(self, processing: Mapping[str, Any], classification: Mapping[str, Any]) -> dict[str, Any]:
        p, c = processing["context"], classification["context"]
        return {"base_asset": p.get("base_asset"), "pair_symbol": p.get("pair_symbol"), "markets": list(MARKETS),
            "timeframes": list(TIMEFRAMES), "data_mode": p.get("data_mode"), "is_demo": p.get("is_demo"),
            "reference_timestamp": p.get("reference_timestamp"), "processing_timestamp": p.get("processing_timestamp"),
            "classification_timestamp": c.get("classification_timestamp"), "data_as_of": p.get("reference_timestamp"),
            "presentation_default_market": self.selected_market, "presentation_default_timeframe": self.selected_timeframe,
            "display_point_limit": self.display_point_limit}

    def build_selectors(self, processing: Mapping[str, Any]) -> dict[str, Any]:
        return {"market": {"id": "market_selector", "selected": self.selected_market,
                "options": [{"id": item, "label": item.title()} for item in MARKETS]},
            "timeframe": {"id": "timeframe_selector", "selected": self.selected_timeframe,
                "options": [{"id": item, "seconds": TIMEFRAME_SECONDS[item],
                    "status": processing["markets"][self.selected_market]["timeframes"][item]["status"]} for item in TIMEFRAMES]}}

    def _kpi(self, identifier: str, title: str, value: Any, unit: str, status: str, reason: Any, timestamp: Any,
             classification: Any, paths: Sequence[str], *, secondary: Mapping[str, Any] | None = None,
             window: str | None = "1h", format_hint: str = "number") -> dict[str, Any]:
        return {"kpi_id": identifier, "title": title, "status": status, "reason": _reason(status, reason), "value": value,
            "unit": unit, "secondary_values": copy.deepcopy(dict(secondary or {})), "timestamp": timestamp,
            "market": self.selected_market, "window": window, "classification": _classification(classification),
            "format_hint": format_hint, "source_paths": list(paths)}

    def build_kpis(self, processing: Mapping[str, Any], classification: Mapping[str, Any]) -> dict[str, Any]:
        market = self.selected_market
        summary = processing["markets"][market]["window_summaries"]["1h"]
        atoms = classification["classifications"]["markets"][market]["window_summaries"]["1h"]["atoms"]
        base = f"processing.markets.{market}.window_summaries.1h"
        cbase = f"classification.classifications.markets.{market}.window_summaries.1h.atoms"
        ratio, ratio_status, ratio_reason = _metric(summary["buy_sell_ratio"], f"{base}.buy_sell_ratio")
        imbalance, imbalance_status, imbalance_reason = _metric(summary["order_flow_imbalance"], f"{base}.order_flow_imbalance")
        efficiency, efficiency_status, efficiency_reason = _metric(summary["flow_efficiency"], f"{base}.flow_efficiency")
        buy_share, _, _ = _metric(summary["buy_share"], f"{base}.buy_share")
        sell_share, _, _ = _metric(summary["sell_share"], f"{base}.sell_share")
        footprint = processing["markets"][market].get("footprint_summaries", {}).get("1h", {})
        footprint_status = _status(footprint.get("status", "unavailable"), "processing.footprint.status")
        price = processing["markets"][market].get("price_vs_vwap", {})
        price_status = _status(price.get("status", "unavailable"), "processing.price_vs_vwap.status")
        price_atom = classification["classifications"]["markets"][market].get("price_vs_vwap")
        source_status = _status(summary.get("status"), f"{base}.status")
        timestamp = _timestamp(summary.get("last_timestamp"), f"{base}.last_timestamp")
        return {
            "delta_1h": self._kpi("delta_1h", "Delta 1H", _number(summary.get("volume_delta_usd"), f"{base}.volume_delta_usd"), "USD", source_status, summary.get("reason"), timestamp, atoms.get("delta_state"), [f"{base}.volume_delta_usd", f"{cbase}.delta_state"], format_hint="currency"),
            "buy_sell_ratio_1h": self._kpi("buy_sell_ratio_1h", "Buy/Sell", ratio, "ratio", ratio_status, ratio_reason, timestamp, atoms.get("buy_sell_pressure_state"), [f"{base}.buy_sell_ratio.value", f"{base}.buy_share.value", f"{base}.sell_share.value", f"{cbase}.buy_sell_pressure_state"], secondary={"buy_share": {"value": buy_share, "unit": "decimal"}, "sell_share": {"value": sell_share, "unit": "decimal"}}),
            "order_flow_1h": self._kpi("order_flow_1h", "Order Flow", imbalance, "decimal", imbalance_status, imbalance_reason, timestamp, atoms.get("order_flow_state"), [f"{base}.order_flow_imbalance.value", f"{cbase}.order_flow_state"]),
            "flow_efficiency_1h": self._kpi("flow_efficiency_1h", "Flow Efficiency", efficiency, "decimal", efficiency_status, efficiency_reason, timestamp, atoms.get("flow_efficiency_state"), [f"{base}.flow_efficiency.value", f"{cbase}.flow_efficiency_state"]),
            "vwap_1h": self._kpi("vwap_1h", "VWAP 1H", _number(footprint.get("vwap_usd"), "processing.footprint.vwap"), "USD", footprint_status, footprint.get("reason"), timestamp, None, [f"processing.markets.{market}.footprint_summaries.1h.vwap_usd"], format_hint="currency"),
            "price_vs_vwap": self._kpi("price_vs_vwap", "Price vs VWAP", _number(price.get("value"), "processing.price_vs_vwap.value"), "decimal", price_status, price.get("reason"), _timestamp(price.get("price_timestamp"), "processing.price_vs_vwap.timestamp"), price_atom, [f"processing.markets.{market}.price_vs_vwap.value", f"classification.classifications.markets.{market}.price_vs_vwap"], window=None),
        }

    def _visual_status(self, source: Mapping[str, Any], count: int) -> tuple[str, str | None]:
        status = _status(source.get("status"), "processing.timeframe.status")
        reason = source.get("reason")
        if count == 0:
            status = "invalid" if status == "invalid" else "unavailable"
            reason = reason or "no_visual_records"
        elif count < self.display_point_limit and status != "invalid":
            status = "partial"
            reason = "insufficient_visual_history" if not reason else f"{reason};insufficient_visual_history"
        return status, _reason(status, reason)

    def build_cvd_chart(self, processing: Mapping[str, Any], market: str) -> dict[str, Any]:
        series = {}
        for timeframe in TIMEFRAMES:
            source = processing["markets"][market]["timeframes"][timeframe]
            records = source["records"]
            points = [{"timestamp": row["timestamp"], "open": _number(row.get("cvd_ohlc_usd", {}).get("open"), "cvd.open"),
                "high": _number(row.get("cvd_ohlc_usd", {}).get("high"), "cvd.high"), "low": _number(row.get("cvd_ohlc_usd", {}).get("low"), "cvd.low"),
                "close": _number(row.get("cvd_ohlc_usd", {}).get("close"), "cvd.close"), "is_partial": row.get("is_partial"),
                "continuity_status": row.get("continuity_status")} for row in records[-self.display_point_limit:]]
            status, reason = self._visual_status(source, len(points))
            series[timeframe] = {"timeframe": timeframe, "seconds": TIMEFRAME_SECONDS[timeframe], "status": status, "reason": reason,
                "records_available": len(records), "records_returned": len(points), "history_truncated": len(records) > self.display_point_limit,
                "points": points, "source_path": f"processing.markets.{market}.timeframes.{timeframe}.records"}
        selected = series[self.selected_timeframe]["points"]
        chart_status = _combine([payload["status"] for payload in series.values()])
        return {"chart_id": f"cvd_{market}", "title": f"CVD {market.title()}", "subtitle": "Cumulative Volume Delta",
            "chart_type": "candlestick", "preferred_representation": "candlestick", "fallback_representation": "line_close",
            "native_ohlc": False, "construction": "derived_from_interval_volume_delta_path", "unit": "USD",
            "status": chart_status, "reason": _reason(chart_status, "chart_series_incomplete"),
            "selected_timeframe": self.selected_timeframe, "current": copy.deepcopy(selected[-1]) if selected else None,
            "series_by_timeframe": series, "source_paths": [f"processing.markets.{market}.timeframes"]}

    def build_delta_chart(self, processing: Mapping[str, Any]) -> dict[str, Any]:
        market, series = self.selected_market, {}
        for timeframe in TIMEFRAMES:
            source = processing["markets"][market]["timeframes"][timeframe]
            records = source["records"]
            points = [{"timestamp": row["timestamp"], "volume_delta_usd": _number(row.get("volume_delta_usd"), "delta.value"),
                "delta_ma_21_usd": _number(row.get("delta_ma_21_usd"), "delta.ma"), "is_partial": row.get("is_partial"),
                "continuity_status": row.get("continuity_status")} for row in records[-self.display_point_limit:]]
            status, reason = self._visual_status(source, len(points))
            series[timeframe] = {"timeframe": timeframe, "seconds": TIMEFRAME_SECONDS[timeframe], "status": status, "reason": reason,
                "records_available": len(records), "records_returned": len(points), "history_truncated": len(records) > self.display_point_limit,
                "points": points, "source_path": f"processing.markets.{market}.timeframes.{timeframe}.records"}
        selected = series[self.selected_timeframe]["points"]
        period = processing["parameters"].get("delta_ma_period", processing["parameters"].get("delta_ma", {}).get("period", 21))
        chart_status = _combine([payload["status"] for payload in series.values()])
        return {"chart_id": "volume_delta", "title": "Delta (Buy-Sell) USD", "chart_type": "bar_with_line_overlay",
            "primary_series": {"field": "volume_delta_usd", "representation": "bar"},
            "overlays": [{"id": "delta_ma_21", "field": "delta_ma_21_usd", "representation": "line", "period": period}],
            "unit": "USD", "market": market, "status": chart_status,
            "reason": _reason(chart_status, "chart_series_incomplete"), "selected_timeframe": self.selected_timeframe,
            "current": copy.deepcopy(selected[-1]) if selected else None, "series_by_timeframe": series,
            "source_paths": [f"processing.markets.{market}.timeframes", "processing.parameters.delta_ma_period"]}

    def build_charts(self, processing: Mapping[str, Any]) -> dict[str, Any]:
        return {"cvd_spot": self.build_cvd_chart(processing, "spot"), "cvd_futures": self.build_cvd_chart(processing, "futures"),
            "cvd_general": self.build_cvd_chart(processing, "general"), "volume_delta": self.build_delta_chart(processing)}

    def _side_widget(self, processing: Mapping[str, Any], window: str) -> dict[str, Any]:
        market = self.selected_market
        source = processing["markets"][market]["window_summaries"][window]
        base = f"processing.markets.{market}.window_summaries.{window}"
        status = _status(source.get("status"), f"{base}.status")
        buy_share, _, _ = _metric(source["buy_share"], f"{base}.buy_share")
        sell_share, _, _ = _metric(source["sell_share"], f"{base}.sell_share")
        return {"widget_id": f"volume_by_side_{window}", "title": f"Volume by Trade Side {window.upper()}", "widget_type": "donut",
            "status": status, "reason": _reason(status, source.get("reason")), "market": market, "window": window,
            "taker_buy_volume_usd": _number(source.get("taker_buy_volume_usd"), f"{base}.buy"),
            "taker_sell_volume_usd": _number(source.get("taker_sell_volume_usd"), f"{base}.sell"),
            "buy_share": buy_share, "sell_share": sell_share, "source_paths": [base]}

    def build_widgets(self, processing: Mapping[str, Any], classification: Mapping[str, Any]) -> dict[str, Any]:
        market = self.selected_market
        summary = processing["markets"][market]["window_summaries"]["1h"]
        metric, status, reason = _metric(summary["order_flow_imbalance"], "processing.order_flow_imbalance")
        atom = classification["classifications"]["markets"][market]["window_summaries"]["1h"]["atoms"]["order_flow_state"]
        agreement = classification["confirmations"]["market_agreement_1h"]
        temporal = classification["confirmations"]["temporal_alignment"][market]
        return {"volume_by_side_1h": self._side_widget(processing, "1h"), "volume_by_side_24h": self._side_widget(processing, "24h"),
            "order_flow_imbalance_1h": {"widget_id": "order_flow_imbalance_1h", "title": "Order Flow Imbalance", "widget_type": "gauge",
                "minimum": -1, "maximum": 1, "value": metric, "state": atom.get("state"), "direction": atom.get("direction"),
                "status": status, "reason": reason, "source_paths": [f"processing.markets.{market}.window_summaries.1h.order_flow_imbalance.value", f"classification.classifications.markets.{market}.window_summaries.1h.atoms.order_flow_state"]},
            "market_agreement_1h": {"widget_id": "market_agreement_1h", "title": "Market Agreement 1H", "widget_type": "state",
                **_copy_classification(agreement), "source_path": "classification.confirmations.market_agreement_1h"},
            "temporal_alignment": {"widget_id": "temporal_alignment", "title": "Temporal Alignment", "widget_type": "state",
                **_copy_classification(temporal), "source_path": f"classification.confirmations.temporal_alignment.{market}"}}

    def build_tables(self, processing: Mapping[str, Any], classification: Mapping[str, Any]) -> dict[str, Any]:
        classified = classification["classifications"]["markets"]
        overview = []
        for market in MARKETS:
            for timeframe in TIMEFRAMES:
                source = processing["markets"][market]["timeframes"][timeframe]
                current = source.get("current")
                atoms = classified[market]["timeframes"][timeframe].get("atoms", {})
                row = {"market": market, "timeframe": timeframe, "timestamp": None, "volume_delta_usd": None,
                    "buy_sell_ratio": None, "order_flow_imbalance": None, "flow_efficiency": None, "cvd_close_usd": None,
                    "delta_state": None, "buy_sell_pressure_state": None, "order_flow_state": None, "cvd_direction_state": None,
                    "flow_efficiency_state": None, "continuity_state": None, "coverage_state": None,
                    "status": source["status"], "reason": _reason(source["status"], source.get("reason")),
                    "source_paths": [f"processing.markets.{market}.timeframes.{timeframe}.current", f"classification.classifications.markets.{market}.timeframes.{timeframe}.atoms"]}
                if isinstance(current, Mapping):
                    row.update({"timestamp": current.get("timestamp"), "volume_delta_usd": copy.deepcopy(current.get("volume_delta_usd")),
                        "buy_sell_ratio": copy.deepcopy(current.get("buy_sell_ratio", {}).get("value")), "order_flow_imbalance": copy.deepcopy(current.get("order_flow_imbalance", {}).get("value")),
                        "flow_efficiency": copy.deepcopy(current.get("flow_efficiency", {}).get("value")), "cvd_close_usd": copy.deepcopy(current.get("cvd_ohlc_usd", {}).get("close"))})
                    for name in ("delta_state", "buy_sell_pressure_state", "order_flow_state", "cvd_direction_state", "flow_efficiency_state", "continuity_state", "coverage_state"):
                        row[name] = copy.deepcopy(atoms.get(name, {}).get("state"))
                else:
                    row["status"] = "invalid" if source["status"] == "invalid" else "unavailable"
                    row["reason"] = source.get("reason") or "current_record_unavailable"
                overview.append(row)
        comparisons = []
        for market in MARKETS:
            for window in ("1h", "24h"):
                source = processing["markets"][market]["window_summaries"][window]
                comparisons.append({"market": market, "window": window, "first_timestamp": copy.deepcopy(source.get("first_timestamp")),
                    "last_timestamp": copy.deepcopy(source.get("last_timestamp")), "volume_delta_usd": copy.deepcopy(source.get("volume_delta_usd")),
                    "buy_sell_ratio": copy.deepcopy(source.get("buy_sell_ratio", {}).get("value")), "buy_share": copy.deepcopy(source.get("buy_share", {}).get("value")),
                    "sell_share": copy.deepcopy(source.get("sell_share", {}).get("value")), "order_flow_imbalance": copy.deepcopy(source.get("order_flow_imbalance", {}).get("value")),
                    "flow_efficiency": copy.deepcopy(source.get("flow_efficiency", {}).get("value")), "coverage_complete": copy.deepcopy(source.get("coverage_complete")),
                    "status": source["status"], "reason": _reason(source["status"], source.get("reason")),
                    "atoms": _copy_classification(classified[market]["window_summaries"][window].get("atoms", {})),
                    "source_paths": [f"processing.markets.{market}.window_summaries.{window}", f"classification.classifications.markets.{market}.window_summaries.{window}.atoms"]})
        overview_status = _combine([row["status"] for row in overview])
        comparison_status = _combine([row["status"] for row in comparisons])
        return {"market_timeframe_overview": {"table_id": "market_timeframe_overview", "title": "Market Timeframe Overview", "status": overview_status, "reason": _reason(overview_status, "market_timeframe_rows_incomplete"), "rows": overview, "source_paths": ["processing.markets", "classification.classifications.markets"]},
            "window_summary_comparison": {"table_id": "window_summary_comparison", "title": "Window Summary Comparison", "status": comparison_status, "reason": _reason(comparison_status, "window_summary_rows_incomplete"), "rows": comparisons, "source_paths": ["processing.markets", "classification.classifications.markets"]}}

    def build_drilldowns(self, processing: Mapping[str, Any], classification: Mapping[str, Any]) -> dict[str, Any]:
        market, timeframe = self.selected_market, self.selected_timeframe
        current = processing["markets"][market]["timeframes"][timeframe].get("current")
        atoms = classification["classifications"]["markets"][market]["timeframes"][timeframe].get("atoms", {})
        footprint_rows = []
        for item in MARKETS:
            source = processing["markets"][item].get("footprint_summaries", {}).get("1h", {})
            footprint_rows.append({"market": item, **{key: copy.deepcopy(source.get(key)) for key in ("vwap_usd", "base_volume", "quote_volume", "records_used", "levels_used", "calculation_basis", "aggregation_scope", "status", "reason")},
                "source_path": f"processing.markets.{item}.footprint_summaries.1h"})
        return {"current_market_detail": {"drilldown_id": "current_market_detail", "market": market, "timeframe": timeframe,
                "current": copy.deepcopy(current), "atoms": _copy_classification(atoms), "source_paths": [f"processing.markets.{market}.timeframes.{timeframe}.current", f"classification.classifications.markets.{market}.timeframes.{timeframe}.atoms"]},
            "market_agreement_detail": {"drilldown_id": "market_agreement_detail", "value": _copy_classification(classification["confirmations"]["market_agreement_1h"]), "source_path": "classification.confirmations.market_agreement_1h"},
            "temporal_alignment_detail": {"drilldown_id": "temporal_alignment_detail", "value": _copy_classification(classification["confirmations"]["temporal_alignment"]), "source_path": "classification.confirmations.temporal_alignment"},
            "footprint_vwap_scope": {"drilldown_id": "footprint_vwap_scope", "rows": footprint_rows, "source_paths": ["processing.markets.general.footprint_summaries.1h", "processing.markets.spot.footprint_summaries.1h", "processing.markets.futures.footprint_summaries.1h"]},
            "classification_snapshots": {"drilldown_id": "classification_snapshots", "value": _copy_classification(classification.get("snapshots", {})), "source_path": "classification.snapshots"}}

    def build_events(self, classification: Mapping[str, Any]) -> dict[str, Any]:
        items = _copy_classification(classification.get("interpreted_events", []))
        if not _sequence(items):
            raise ValueError("invalid_interpreted_events")
        statuses = []
        reasons = []
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("availability"), Mapping):
                raise ValueError("invalid_interpreted_event")
            item_status = _status(item["availability"].get("status"), "classification.interpreted_events.availability")
            statuses.append(item_status)
            if item_status != "available":
                reasons.append(_reason(item_status, item["availability"].get("reason")))
        status = _combine(statuses) if statuses else "available"
        reason = None if status == "available" else ";".join(sorted(set(reasons)))
        return {"id": "recent_events", "status": status, "reason": reason, "items": items,
            "source_path": "classification.interpreted_events"}

    def _inventory(self, selectors: Mapping[str, Any], kpis: Mapping[str, Any], charts: Mapping[str, Any], widgets: Mapping[str, Any],
                   tables: Mapping[str, Any], drilldowns: Mapping[str, Any], events: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        required_objects = {"selectors.market": selectors["market"], "selectors.timeframe": selectors["timeframe"],
            **{f"kpis.{key}": value for key, value in kpis.items()}, **{f"charts.{key}": value for key, value in charts.items()},
            **{f"widgets.{key}": widgets[key] for key in ("volume_by_side_1h", "volume_by_side_24h", "order_flow_imbalance_1h")},
            **{f"tables.{key}": value for key, value in tables.items()}}
        optional_objects = {**{f"widgets.{key}": widgets[key] for key in ("market_agreement_1h", "temporal_alignment")},
            **{f"drilldowns.{key}": value for key, value in drilldowns.items()}, "events.recent_events": events}
        def entry(obj: Mapping[str, Any], name: str) -> dict[str, Any]:
            status = obj.get("status", obj.get("availability", {}).get("status", "available"))
            if status not in VALID_SOURCE_STATUS:
                status = "available"
            paths = obj.get("source_paths", [obj["source_path"]] if "source_path" in obj else [])
            return _availability(status, obj.get("reason"), paths or ["processing.markets"])
        return ({key: entry(value, key) for key, value in required_objects.items()},
                {key: entry(value, key) for key, value in optional_objects.items()})

    def evaluate_availability(self, processing: Mapping[str, Any], classification: Mapping[str, Any], required: Mapping[str, Any], optional: Mapping[str, Any]) -> dict[str, Any]:
        markets = {}
        for market in MARKETS:
            statuses = [processing["markets"][market]["timeframes"][timeframe]["status"] for timeframe in TIMEFRAMES]
            status = _combine(statuses)
            markets[market] = _availability(status, None if status == "available" else "market_data_incomplete", [f"processing.markets.{market}"])
        timeframes = {}
        for timeframe in TIMEFRAMES:
            statuses = [processing["markets"][market]["timeframes"][timeframe]["status"] for market in MARKETS]
            status = _combine(statuses)
            timeframes[timeframe] = _availability(status, None if status == "available" else "timeframe_data_incomplete", [f"processing.markets.{market}.timeframes.{timeframe}" for market in MARKETS])
        return {"required": copy.deepcopy(required), "optional": copy.deepcopy(optional), "markets": markets, "timeframes": timeframes,
            "source_contracts": {"processing": _availability("available" if processing["quality"]["status"] == "ok" else processing["quality"]["status"], None if processing["quality"]["status"] == "ok" else "source_quality_incomplete", ["processing.quality"]),
                "classification": _availability("available" if classification["quality"]["status"] == "ok" else classification["quality"]["status"], None if classification["quality"]["status"] == "ok" else "source_quality_incomplete", ["classification.quality"])}}

    def evaluate_quality(self, processing: Mapping[str, Any], classification: Mapping[str, Any], required: Mapping[str, Any], optional: Mapping[str, Any], charts: Mapping[str, Any]) -> dict[str, Any]:
        required_statuses = {key: value["status"] for key, value in required.items()}
        optional_statuses = {key: value["status"] for key, value in optional.items()}
        series = {}
        for chart_id, chart in charts.items():
            for timeframe, payload in chart["series_by_timeframe"].items():
                series[f"{chart_id}.{timeframe}"] = {key: copy.deepcopy(payload[key]) for key in ("records_available", "records_returned", "history_truncated", "status", "reason")}
                series[f"{chart_id}.{timeframe}"]["target_records"] = self.display_point_limit
        source_statuses = [processing["quality"]["status"], classification["quality"]["status"]]
        invalid = "invalid" in source_statuses or "invalid" in required_statuses.values()
        incomplete = any(value != "available" for value in required_statuses.values()) or any(item["records_returned"] < self.display_point_limit for item in series.values()) or "partial" in source_statuses
        status = "invalid" if invalid else ("partial" if incomplete else "ok")
        warnings = sorted({f"required:{key}:{value}" for key, value in required_statuses.items() if value != "available"} |
            {f"source_quality:{name}:{value}" for name, value in zip(("processing", "classification"), source_statuses) if value != "ok"} |
            {f"visual_density:{key}:{value['records_returned']}" for key, value in series.items() if value["records_returned"] < self.display_point_limit})
        errors = sorted(item for item in warnings if ":invalid" in item)
        return {"status": status, "contract_complete": True, "data_complete": all(value == "available" for value in required_statuses.values()),
            "source_quality": {"processing": processing["quality"]["status"], "classification": classification["quality"]["status"]},
            "builder_quality": {"status": status, "warnings": warnings, "errors": errors}, "required_statuses": required_statuses,
            "optional_statuses": optional_statuses, "visual_density": {"display_point_limit": self.display_point_limit, "series": series},
            "strict_json": True, "warnings": warnings, "errors": errors}

    def build_badges(self, context: Mapping[str, Any], quality: Mapping[str, Any]) -> list[dict[str, Any]]:
        badges = []
        if context["data_mode"] == "synthetic" and context["is_demo"] is True:
            badges.append({"id": "demo", "text": "DEMO", "status": "active"})
        badges.append({"id": "data_quality", "text": quality["status"].upper(), "status": quality["status"]})
        return badges

    def build_operational_status(self, context: Mapping[str, Any], quality: Mapping[str, Any]) -> dict[str, Any]:
        statuses = quality["required_statuses"]
        return {"state": {"ok": "operational", "partial": "degraded", "invalid": "blocked"}[quality["status"]],
            "quality_status": quality["status"], "data_mode": context["data_mode"], "is_demo": context["is_demo"],
            "data_as_of": context["data_as_of"], "selected_market": self.selected_market, "selected_timeframe": self.selected_timeframe,
            "required_components_available": sum(value == "available" for value in statuses.values()), "required_components_total": len(statuses),
            "warnings": copy.deepcopy(quality["warnings"]), "errors": copy.deepcopy(quality["errors"])}

    def run(self, bundle: Mapping[str, Any]) -> dict[str, Any]:
        self.validate_bundle(bundle)
        processing, classification = bundle["processing"], bundle["classification"]
        context = self.build_context(processing, classification)
        selectors = self.build_selectors(processing)
        kpis = self.build_kpis(processing, classification)
        charts = self.build_charts(processing)
        widgets = self.build_widgets(processing, classification)
        tables = self.build_tables(processing, classification)
        drilldowns = self.build_drilldowns(processing, classification)
        events = self.build_events(classification)
        required, optional = self._inventory(selectors, kpis, charts, widgets, tables, drilldowns, events)
        availability = self.evaluate_availability(processing, classification, required, optional)
        quality = self.evaluate_quality(processing, classification, required, optional, charts)
        output = {"schema": {"id": SCREEN_SCHEMA, "version": SCREEN_VERSION},
            "screen": {"id": SCREEN_ID, "family": FAMILY, "route": SCREEN_ROUTE, "title": SCREEN_TITLE, "subtitle": SCREEN_SUBTITLE},
            "stage": "screen_contract", "mode": processing["mode"], "context": context,
            "badges": self.build_badges(context, quality), "selectors": selectors,
            "operational_status": self.build_operational_status(context, quality), "kpis": kpis, "charts": charts,
            "widgets": widgets, "tables": tables, "drilldowns": drilldowns, "events": events,
            "availability": availability, "quality": quality}
        _validated_paths(output)
        json.dumps(output, ensure_ascii=False, allow_nan=False)
        return output


def build_cvd_volume_orderflow_contract(bundle: Mapping[str, Any], *, selected_market: str = DEFAULT_MARKET,
                                        selected_timeframe: str = DEFAULT_TIMEFRAME,
                                        display_point_limit: int = DISPLAY_POINT_LIMIT) -> dict[str, Any]:
    return CvdVolumeOrderflowContractBuilder(selected_market=selected_market, selected_timeframe=selected_timeframe,
        display_point_limit=display_point_limit).run(bundle)
