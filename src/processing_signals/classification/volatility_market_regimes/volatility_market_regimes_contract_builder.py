from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from copy            import deepcopy
from datetime        import datetime
from numbers         import Integral, Real
from typing          import Any


DISPLAY_RANGE_OPTIONS      = ("1h", "4h", "1d", "7d", "30d")
DEFAULT_DISPLAY_RANGE      = "7d"
MAX_HOURLY_DISPLAY_SECONDS = 30 * 86400
MAX_DAILY_DISPLAY_DAYS     = 30
_MODES                     = {"bootstrap", "incremental", "recovery"}
_AVAILABILITY              = {"available", "partial", "unavailable", "invalid"}
_RANGE_SECONDS             = {"1h": 3600, "4h": 14400, "1d": 86400, "7d": 604800, "30d": 2592000}
_REGIME_LABELS             = {"low_vol": "Low Vol", "normal": "Normal", "high_vol": "High Vol"}
_REGIME_COLORS             = {"low_vol": "regime_low_vol", "normal": "regime_normal", "high_vol": "regime_high_vol"}
_CONFIDENCE_COLORS         = {"high": "confidence_high", "medium": "confidence_medium", "low": "confidence_low"}
_POSITIONING_COLORS        = {"short_bias": "positioning_short", "balanced": "positioning_balanced", "long_bias": "positioning_long"}
_SPREAD_COLORS             = {"realized_below_implied": "spread_negative", "balanced": "spread_balanced", "realized_above_implied": "spread_positive"}


def _strict_number(value: Any, path: str, nullable: bool = True) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{path}:finite_number_required")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path}:finite_number_required")
    return 0.0 if result == 0 else result


def _iso_timezone(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}:timezone_iso8601_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path}:timezone_iso8601_required") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{path}:timezone_iso8601_required")
    return value


def validate_runtime_context(runtime_context: Any) -> None:
    if not isinstance(runtime_context, Mapping):
        raise ValueError("runtime_context:mapping_required")
    data_mode = runtime_context.get("data_mode")
    is_demo   = runtime_context.get("is_demo")
    if data_mode not in {"synthetic", "live"} or type(is_demo) is not bool:
        raise ValueError("runtime_context:data_mode_or_is_demo_invalid")
    if (data_mode == "synthetic") != is_demo:
        raise ValueError("runtime_context:data_mode_is_demo_mismatch")
    _iso_timezone(runtime_context.get("generated_at"), "runtime_context.generated_at")
    _iso_timezone(runtime_context.get("updated_at"), "runtime_context.updated_at")


def validate_volatility_market_regimes_builder_inputs(processing: Any, classification: Any, runtime_context: Any, selected_range: str = DEFAULT_DISPLAY_RANGE) -> None:
    for name, contract, stage in (("processing", processing, "processing"), ("classification", classification, "classification")):
        if not isinstance(contract, Mapping):
            raise ValueError(f"{name}:mapping_required")
        if contract.get("family") != "volatility_market_regimes" or contract.get("stage") != stage or contract.get("version") != "0.1.0":
            raise ValueError(f"{name}:identity_invalid")
        if contract.get("mode") not in _MODES or not isinstance(contract.get("context"), Mapping):
            raise ValueError(f"{name}:mode_or_context_invalid")
    if selected_range not in DISPLAY_RANGE_OPTIONS:
        raise ValueError("selected_range:invalid")
    validate_runtime_context(runtime_context)
    for field in ("mode",):
        if processing.get(field) != classification.get(field):
            raise ValueError(f"builder_contract_mismatch:{field}")
    for field in ("reference_timestamp", "input_execution_timestamp", "asset", "symbol", "exchange", "base_interval"):
        if processing["context"].get(field) != classification["context"].get(field):
            raise ValueError(f"builder_contract_mismatch:{field}")
    p_features = processing.get("features")
    c_classes  = classification.get("classifications")
    if not isinstance(p_features, Mapping) or not all(isinstance(p_features.get(name), Mapping) for name in ("positioning", "volatility_comparison", "spread_metrics", "daily_regime_basis")):
        raise ValueError("processing:required_features_missing")
    if not isinstance(c_classes, Mapping) or not all(isinstance(c_classes.get(name), Mapping) for name in ("daily_regimes", "positioning", "spread_context")):
        raise ValueError("classification:required_classifications_missing")
    summaries = classification.get("summaries")
    if not isinstance(summaries, Mapping) or not isinstance(summaries.get("regime_distribution"), Mapping) or not isinstance(summaries.get("regime_statistics"), Sequence):
        raise ValueError("classification:required_summaries_missing")
    if not isinstance(classification.get("interpreted_events"), Mapping) or not isinstance(processing.get("quality"), Mapping) or not isinstance(classification.get("quality"), Mapping):
        raise ValueError("builder:quality_or_events_missing")


def _history_metadata(all_records: Sequence[Mapping[str, Any]], returned: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "records_available": len(all_records), "records_returned": len(returned), "history_truncated": len(returned) < len(all_records),
        "first_available_timestamp": all_records[0]["timestamp"] if all_records else None,
        "last_available_timestamp": all_records[-1]["timestamp"] if all_records else None,
        "first_returned_timestamp": returned[0]["timestamp"] if returned else None,
        "last_returned_timestamp": returned[-1]["timestamp"] if returned else None,
    }


def _hourly_tail(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted((deepcopy(dict(record)) for record in records), key=lambda record: record["timestamp"])
    if not ordered:
        return ordered, []
    start = ordered[-1]["timestamp"] - MAX_HOURLY_DISPLAY_SECONDS
    return ordered, [record for record in ordered if record["timestamp"] >= start]


def _daily_tail(records: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted((deepcopy(dict(record)) for record in records), key=lambda record: record["timestamp"])
    return ordered, ordered[-MAX_DAILY_DISPLAY_DAYS:]


def build_volatility_market_regimes_screen_context(processing: Mapping[str, Any], classification: Mapping[str, Any], runtime_context: Mapping[str, Any], selected_range: str) -> dict[str, Any]:
    context    = processing["context"]
    candidates = [
        processing["features"]["positioning"].get("last_available_timestamp"),
        processing["features"]["volatility_comparison"].get("last_available_timestamp"),
        (classification["classifications"]["daily_regimes"].get("current") or {}).get("timestamp"),
    ]
    data_as_of = max((value for value in candidates if isinstance(value, Integral) and not isinstance(value, bool)), default=None)
    windows    = {name: {"start_timestamp": data_as_of - seconds if data_as_of is not None else None, "end_timestamp": data_as_of} for name, seconds in _RANGE_SECONDS.items()}
    return {
        "symbol": context.get("symbol"), "asset": context.get("asset"), "exchange": context.get("exchange"), "base_interval": context.get("base_interval"),
        "default_display_range": DEFAULT_DISPLAY_RANGE, "selected_display_range": selected_range, "available_display_ranges": list(DISPLAY_RANGE_OPTIONS),
        "data_mode": runtime_context["data_mode"], "is_demo": runtime_context["is_demo"], "generated_at": runtime_context["generated_at"], "updated_at": runtime_context["updated_at"],
        "reference_timestamp": context.get("reference_timestamp"), "input_execution_timestamp": context.get("input_execution_timestamp"), "data_as_of": data_as_of,
        "units": {"volatility": "percent", "spread": "volatility_points", "positioning_ratio": "ratio", "positioning_percent": "percent",
                  "confidence": "decimal", "empirical_share": "decimal", "persistence": "days"},
        "history_policy": {"calculation": "full_available_history", "presentation": "tail_window", "max_hourly_display_seconds": 2592000, "max_daily_display_days": 30},
        "range_windows": windows,
    }


def build_volatility_market_regimes_badges(runtime_context: Mapping[str, Any]) -> list[dict[str, str]]:
    return [{"badge_id": "demo", "text": "DEMO", "status": "active"}] if runtime_context["data_mode"] == "synthetic" else []


def build_volatility_market_regimes_selectors(selected_range: str) -> dict[str, Any]:
    return {"display_range": {"selector_id": "volatility_market_regimes_display_range", "selected": selected_range,
                              "options": list(DISPLAY_RANGE_OPTIONS), "behavior": "timestamp_window_filter"}}


def _empty_kpi(metric_id: str, label: str, unit: str, invalid: bool = False) -> dict[str, Any]:
    return {"metric_id": metric_id, "label": label, "value": None, "display_value": "--", "unit": unit,
            "status": "invalid" if invalid else "unavailable", "reason": "classification_invalid" if invalid else "metric_unavailable",
            "color_token": "state_invalid" if invalid else "state_unavailable"}


def build_current_regime_kpi(daily: Mapping[str, Any]) -> dict[str, Any]:
    current = daily.get("current")
    if not current:
        return _empty_kpi("current_regime", "Current Regime", "state", daily.get("status") == "invalid")
    regime = current.get("regime")
    return {"metric_id": "current_regime", "label": "Current Regime", "value": regime, "display_value": _REGIME_LABELS.get(regime, "--"), "unit": "state",
            "status": current.get("status", daily.get("status")), "reason": current.get("reason"), "color_token": _REGIME_COLORS.get(regime, "state_unavailable")}


def build_confidence_kpi(daily: Mapping[str, Any]) -> dict[str, Any]:
    current = daily.get("current")
    if not current or current.get("confidence_score") is None:
        return _empty_kpi("confidence", "Confidence", "decimal", daily.get("status") == "invalid")
    score = _strict_number(current["confidence_score"], "confidence_score", False)
    return {"metric_id": "confidence", "label": "Confidence", "value": score, "display_value": f"{score:.0%}", "unit": "decimal",
            "status": current.get("status", daily.get("status")), "reason": current.get("reason"),
            "color_token": _CONFIDENCE_COLORS.get(current.get("confidence_state"), "state_unavailable")}


def build_spread_7d_kpi(spread: Mapping[str, Any]) -> dict[str, Any]:
    value = _strict_number(spread.get("value"), "spread.value")
    if value is None:
        item = _empty_kpi("spread_7d", "Spread (7D)", "volatility_points", spread.get("status") == "invalid")
        item["reason"] = spread.get("reason") or item["reason"]
    else:
        display = f"{value:+.1f} vol pts" if value > 0 else f"{value:.1f} vol pts"
        item    = {"metric_id": "spread_7d", "label": "Spread (7D)", "value": value, "display_value": display, "unit": "volatility_points",
                "status": spread.get("status"), "reason": spread.get("reason"), "color_token": _SPREAD_COLORS.get(spread.get("spread_state"), "state_unavailable")}
    item["metadata"] = {field: deepcopy(spread.get(field)) for field in ("basis", "records_used", "coverage", "window_start_timestamp", "window_end_timestamp")}
    return item


def build_persistence_kpi(daily: Mapping[str, Any]) -> dict[str, Any]:
    value = daily.get("current_persistence_days")
    if value is None or not daily.get("current"):
        return _empty_kpi("persistence", "Persistence", "days", daily.get("status") == "invalid")
    return {"metric_id": "persistence", "label": "Persistence", "value": int(value), "display_value": f"{value} day" if value == 1 else f"{value} days", "unit": "days",
            "status": daily["current"].get("status", daily.get("status")), "reason": daily["current"].get("reason"),
            "color_token": _REGIME_COLORS.get(daily["current"].get("regime"), "state_unavailable")}


def build_volatility_market_regimes_kpis(classification: Mapping[str, Any]) -> dict[str, Any]:
    daily  = classification["classifications"]["daily_regimes"]
    spread = classification["classifications"]["spread_context"]
    return {"items": [build_current_regime_kpi(daily), build_confidence_kpi(daily), build_spread_7d_kpi(spread), build_persistence_kpi(daily)]}


def build_positioning_ratio_chart(processing_feature: Mapping[str, Any], classification_feature: Mapping[str, Any]) -> dict[str, Any]:
    all_records, returned = _hourly_tail(processing_feature.get("records", []))
    semantic = {record["timestamp"]: record for record in classification_feature.get("records", []) if isinstance(record, Mapping)}
    missing  = False
    records  = []
    for raw in returned:
        classified = semantic.get(raw["timestamp"])
        missing    |= classified is None
        state       = classified.get("positioning_state") if classified else None
        records.append({"timestamp": raw["timestamp"], "long_short_ratio": deepcopy(raw.get("long_short_ratio")), "long_percent": deepcopy(raw.get("long_percent")),
                        "short_percent": deepcopy(raw.get("short_percent")), "net_long_percentage_points": deepcopy(raw.get("net_long_percentage_points")),
                        "positioning_state": state, "crowding_state": classified.get("crowding_state") if classified else None,
                        "color_token": _POSITIONING_COLORS.get(state)})
    status   = processing_feature.get("status")
    reason   = processing_feature.get("reason")
    warnings = []
    if missing and status == "available":
        status, reason = "partial", "positioning_classification_missing"
        warnings.append("positioning_classification_missing")
    return {"chart_id": "long_short_positioning_ratio", "title": "Long / Short Positioning Ratio", "chart_type": "line", "status": status, "reason": reason,
            "unit": "ratio", "reference_lines": [{"value": 1.0, "label": "Balanced"}], "source": deepcopy(processing_feature.get("source")),
            "selector_behavior": "timestamp_window_filter", "records": records, "warnings": warnings, **_history_metadata(all_records, records)}


def build_volatility_comparison_chart(feature: Mapping[str, Any]) -> dict[str, Any]:
    all_records, returned = _hourly_tail(feature.get("records", []))
    fields  = ("timestamp", "realized_volatility_percent", "implied_open_percent", "implied_high_percent", "implied_low_percent", "implied_close_percent", "spread_volatility_points", "pair_status")
    records = [{field: deepcopy(record.get(field)) for field in fields} for record in returned]
    return {"chart_id": "realized_implied_volatility", "title": "Realized vs Implied Volatility", "chart_type": "multi_line",
            "status": feature.get("status"), "reason": feature.get("reason"),
            "series": [{"series_id": "realized_volatility", "label": "Realized Vol", "unit": "percent", "source": {"provider": "glassnode", "endpoint_id": "realized_volatility"}},
                       {"series_id": "implied_volatility", "label": "Implied Vol", "unit": "percent", "source": {"provider": "deribit", "endpoint_id": "volatility_index", "basis": "close"}}],
            "selector_behavior": "timestamp_window_filter", "records": records, "current": deepcopy(feature.get("current")), **_history_metadata(all_records, records)}


def build_visible_regime_events(interpreted_events: Mapping[str, Any], start_timestamp: int | None, end_timestamp: int | None) -> dict[str, Any]:
    source_by_id = interpreted_events.get("by_id")
    source_ids   = interpreted_events.get("regime_transition_ids")
    if not isinstance(source_by_id, Mapping) or not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes)):
        raise ValueError("events:structure_invalid")
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("events:duplicate_event_id")
    selected = []
    by_id    = {}
    previous = None
    for event_id in source_ids:
        event = source_by_id.get(event_id)
        if not isinstance(event, Mapping) or event.get("event_id") != event_id:
            raise ValueError("events:broken_reference")
        timestamp = event.get("timestamp")
        if previous is not None and timestamp < previous:
            raise ValueError("events:not_chronological")
        previous = timestamp
        if start_timestamp is not None and end_timestamp is not None and start_timestamp <= timestamp <= end_timestamp:
            selected.append(event_id)
            by_id[event_id] = deepcopy(dict(event))
    return {"by_id": by_id, "regime_transition_ids": selected}


def build_regime_timeline_chart(feature: Mapping[str, Any], events: Mapping[str, Any]) -> dict[str, Any]:
    all_records, returned = _daily_tail(feature.get("records", []))
    by_timestamp = {}
    for event_id in events["regime_transition_ids"]:
        by_timestamp.setdefault(events["by_id"][event_id]["timestamp"], []).append(event_id)
    records = []
    for raw in returned:
        regime = raw.get("regime")
        records.append({"timestamp": raw["timestamp"], "data_as_of": deepcopy(raw.get("data_as_of")), "regime": regime,
                        "regime_label": _REGIME_LABELS.get(regime, "--"), "confidence_score": deepcopy(raw.get("confidence_score")),
                        "confidence_state": raw.get("confidence_state"), "persistence_days": raw.get("persistence_days"),
                        "agreement_state": raw.get("agreement_state"), "status": raw.get("status"), "reason": raw.get("reason"),
                        "color_token": _REGIME_COLORS.get(regime, "state_invalid" if raw.get("status") == "invalid" else "state_unavailable"),
                        "event_ids": list(by_timestamp.get(raw["timestamp"], []))})
    return {"chart_id": "regime_timeline", "title": "Regime Timeline", "chart_type": "regime_timeline", "status": feature.get("status"), "reason": feature.get("reason"),
            "unit": "state", "selector_behavior": "timestamp_window_filter", "records": records, **_history_metadata(all_records, records)}


def build_regime_distribution_chart(distribution: Mapping[str, Any]) -> dict[str, Any]:
    order = ("low_vol", "normal", "high_vol")
    items = []
    for regime in order:
        share = _strict_number(distribution.get("shares", {}).get(regime), f"distribution.{regime}.share")
        items.append({"regime": regime, "label": _REGIME_LABELS[regime], "count": distribution.get("counts", {}).get(regime, 0), "share": share,
                      "display_share": f"{share:.1%}" if share is not None else "--", "color_token": _REGIME_COLORS[regime]})
    return {"chart_id": "regime_distribution", "title": "Regime Distribution", "chart_type": "donut", "status": distribution.get("status"), "reason": distribution.get("reason"),
            "basis": distribution.get("basis"), "window": "full_history", "classified_days": distribution.get("classified_days", 0),
            "selector_behavior": "fixed_full_history_summary", "items": items}


def build_volatility_market_regimes_charts(processing: Mapping[str, Any], classification: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    daily_records = classification["classifications"]["daily_regimes"].get("records", [])
    _, visible_daily = _daily_tail(daily_records)
    start  = visible_daily[0]["timestamp"] if visible_daily else None
    end    = visible_daily[-1]["timestamp"] if visible_daily else None
    events = build_visible_regime_events(classification["interpreted_events"], start, end)
    charts = {
        "positioning_ratio": build_positioning_ratio_chart(processing["features"]["positioning"], classification["classifications"]["positioning"]),
        "volatility_comparison": build_volatility_comparison_chart(processing["features"]["volatility_comparison"]),
        "regime_timeline": build_regime_timeline_chart(classification["classifications"]["daily_regimes"], events),
        "regime_distribution": build_regime_distribution_chart(classification["summaries"]["regime_distribution"]["full_history"]),
    }
    return charts, events


def build_market_regime_table(statistics: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    indexed = {row.get("regime"): row for row in statistics}
    rows    = []
    for regime in ("low_vol", "normal", "high_vol"):
        source = indexed.get(regime, {})
        share  = _strict_number(source.get("empirical_share"), f"statistics.{regime}.share")
        rows.append({"row_id": f"regime:{regime}", "regime": regime, "label": _REGIME_LABELS[regime], "color_token": _REGIME_COLORS[regime],
                     "classified_days": source.get("classified_days", 0), "empirical_share": share, "display_share": f"{share:.1%}" if share is not None else "--",
                     "episode_count": source.get("episode_count", 0), "average_episode_days": deepcopy(source.get("average_episode_days")),
                     "maximum_episode_days": source.get("maximum_episode_days"), "current_episode_days": source.get("current_episode_days", 0), "is_current": bool(source.get("is_current"))})
    status = "available" if all(indexed.get(regime) for regime in ("low_vol", "normal", "high_vol")) else "partial"
    return {"table_id": "market_regime_table", "title": "Market Regime Table", "status": status, "reason": None if status == "available" else "regime_statistics_incomplete",
            "share_basis": "empirical_classified_day_share", "columns": ["regime", "empirical_share", "classified_days", "episode_count", "average_episode_days", "maximum_episode_days", "current_episode_days"], "rows": rows}


def _combine_status(*statuses: str) -> str:
    for status in ("invalid", "unavailable", "partial", "available"):
        if status in statuses:
            return status
    return "invalid"


def build_source_status_widget(processing: Mapping[str, Any], classification: Mapping[str, Any]) -> dict[str, Any]:
    availability = processing.get("source_availability", {})
    mapping      = (("coinglass", "CoinGlass", "coinglass.top_position_ratio"), ("glassnode", "Glassnode", "glassnode.realized_volatility"), ("deribit", "Deribit", "deribit.volatility_index"))
    items        = []
    for provider_id, label, key in mapping:
        source = availability.get(key, {})
        status = source.get("status", "unavailable")
        items.append({"provider_id": provider_id, "label": label, "status": status, "reason": source.get("reason") or ("source_unavailable" if status != "available" else None),
                      "data_as_of": source.get("source_data_as_of")})
    internal_status = _combine_status(processing["quality"].get("status") if processing["quality"].get("status") != "ok" else "available",
                                      classification["quality"].get("status") if classification["quality"].get("status") != "ok" else "available")
    items.append({"provider_id": "internal", "label": "Internal", "status": internal_status, "reason": None if internal_status == "available" else "internal_quality_degraded",
                  "data_as_of": classification["classifications"]["daily_regimes"].get("source_data_as_of")})
    status = _combine_status(*(item["status"] for item in items))
    return {"widget_id": "source_status", "status": status, "reason": None if status == "available" else "one_or_more_sources_degraded", "items": items}


def evaluate_volatility_market_regimes_screen_quality(screen_parts: Mapping[str, Any], errors: Sequence[str] = (), warnings: Sequence[str] = ()) -> dict[str, Any]:
    availability = {}
    for item in screen_parts["kpis"].get("items", []):
        availability[f"kpis.{item['metric_id']}"] = item.get("status")
    for name, chart in screen_parts["charts"].items():
        availability[f"charts.{name}"] = chart.get("status")
    availability["tables.market_regime_table"] = screen_parts["tables"]["market_regime_table"].get("status")
    availability["widgets.source_status"]       = screen_parts["widgets"]["source_status"].get("status")
    statuses          = list(availability.values())
    contract_complete = not errors
    data_complete     = contract_complete and all(status == "available" for status in statuses)
    status            = "invalid" if errors or "invalid" in statuses else "ok" if data_complete else "partial"
    return {"status": status, "contract_complete": contract_complete, "data_complete": data_complete, "availability": availability,
            "missing_fields": [], "warnings": sorted(set(warnings)), "errors": list(errors)}


def _invalid_screen(error: str) -> dict[str, Any]:
    return {"family": "volatility_market_regimes", "screen": "volatility_market_regimes", "schema_version": "0.1.0", "context": {}, "badges": [],
            "selectors": {}, "kpis": {"items": []}, "charts": {}, "tables": {}, "widgets": {}, "events": {"by_id": {}, "regime_transition_ids": []},
            "quality": {"status": "invalid", "contract_complete": False, "data_complete": False, "availability": {}, "missing_fields": [], "warnings": [], "errors": [error]}}


class VolatilityMarketRegimesContractBuilder:
    def build(self, processing_contract: Any, classification_contract: Any, *, runtime_context: Any, selected_range: str = DEFAULT_DISPLAY_RANGE) -> dict[str, Any]:
        try:
            validate_volatility_market_regimes_builder_inputs(processing_contract, classification_contract, runtime_context, selected_range)
            context = build_volatility_market_regimes_screen_context(processing_contract, classification_contract, runtime_context, selected_range)
            kpis    = build_volatility_market_regimes_kpis(classification_contract)
            charts, events = build_volatility_market_regimes_charts(processing_contract, classification_contract)
            parts = {"kpis": kpis, "charts": charts, "tables": {"market_regime_table": build_market_regime_table(classification_contract["summaries"]["regime_statistics"])},
                     "widgets": {"source_status": build_source_status_widget(processing_contract, classification_contract)}}
            warnings = [warning for chart in charts.values() for warning in chart.get("warnings", [])]
            quality  = evaluate_volatility_market_regimes_screen_quality(parts, warnings=warnings)
            screen   = {"family": "volatility_market_regimes", "screen": "volatility_market_regimes", "schema_version": "0.1.0", "context": context,
                      "badges": build_volatility_market_regimes_badges(runtime_context), "selectors": build_volatility_market_regimes_selectors(selected_range),
                      **parts, "events": events, "quality": quality}
            json.dumps(screen, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False)
            return screen
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            return _invalid_screen(str(exc))


def build_volatility_market_regimes_screen(
    processing_contract: Any, classification_contract: Any, *, runtime_context: Any, selected_range: str = DEFAULT_DISPLAY_RANGE,
) -> dict[str, Any]:
    return VolatilityMarketRegimesContractBuilder().build(processing_contract, classification_contract, runtime_context=runtime_context, selected_range=selected_range)
