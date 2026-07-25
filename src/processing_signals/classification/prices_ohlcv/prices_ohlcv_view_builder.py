from __future__ import annotations

from copy     import deepcopy
from datetime import UTC, datetime
import json
from typing   import Any, Mapping

from .prices_ohlcv_contract_builder import (
    MARKET_ORDER,
    TIMEFRAME_ORDER,
    build_indicators_metrics_table,
    build_prices_kpis,
    build_prices_widgets,
    build_statistical_performance_table,
    build_technical_bias_table,
)


def _selected_data_as_of(processing_output: Mapping[str, Any], market: str, timeframe: str) -> str | None:
    records = processing_output.get("markets", {}).get(market, {}).get("timeframes", {}).get(timeframe, {}).get("records", [])
    return datetime.fromtimestamp(int(records[-1]["timestamp"]), tz=UTC).isoformat() if records else None


def _selected_comparison(processing_output: Mapping[str, Any], classification_output: Mapping[str, Any], timeframe: str) -> dict[str, Any]:
    numeric_source = processing_output.get("features", {}).get("spot_futures_comparison", {}).get("by_timeframe", {}).get(timeframe, {})
    numeric        = {"current": deepcopy(numeric_source.get("current", {}))}
    classification = classification_output.get("market_relationship", {})
    if classification.get("timeframe") != timeframe:
        classification = {"status": "unavailable", "reason": "classification_not_available_for_selected_timeframe"}
    return {"timeframe": timeframe, "numeric": deepcopy(numeric), "classification": deepcopy(classification)}


def _selected_view_quality(*, kpis: Mapping[str, Any], widgets: Mapping[str, Any], tables: Mapping[str, Any], serializable: bool) -> dict[str, Any]:
    kpi_items         = list(kpis.get("items", []))
    widget_items      = list(widgets.values())
    contract_complete = serializable and all(name in tables for name in ("indicator_package", "technical_bias", "statistical_performance"))
    data_complete     = all(item.get("status") == "available" for item in kpi_items) and all(item.get("status") == "available" for item in widget_items)
    return {"status": "ok" if contract_complete else "invalid", "contract_complete": contract_complete, "data_complete": data_complete,
            "availability": {"kpis_available": sum(item.get("status") == "available" for item in kpi_items), "kpis_total": len(kpi_items),
                             "widgets_available": sum(item.get("status") == "available" for item in widget_items), "widgets_total": len(widget_items),
                             "tables_available": sum(bool(table.get("rows")) for table in tables.values()), "tables_total": len(tables)},
            "missing_fields": [], "warnings": [], "errors": [] if serializable else ["selected view is not strictly JSON serializable"]}


def build_prices_selected_view(processing_output: Mapping[str, Any], classification_output: Mapping[str, Any], *, market: str, timeframe: str) -> dict[str, Any]:
    """Build a small selector response from already-computed Prices state."""
    if processing_output.get("family") != "prices_ohlcv" or processing_output.get("stage") != "processing":
        raise ValueError("Selected Prices view requires a prices_ohlcv processing contract")
    if classification_output.get("family") != "prices_ohlcv" or classification_output.get("stage") != "classification":
        raise ValueError("Selected Prices view requires a prices_ohlcv classification contract")
    if market not in MARKET_ORDER:
        raise ValueError(f"Unsupported Prices market: {market}")
    if timeframe not in TIMEFRAME_ORDER:
        raise ValueError(f"Unsupported Prices timeframe: {timeframe}")
    selection  = {"selected_market": market, "selected_timeframe": timeframe, "available_markets": list(MARKET_ORDER), "available_timeframes": list(TIMEFRAME_ORDER)}
    kpis       = build_prices_kpis(processing_output, selection)
    widgets    = build_prices_widgets(processing_output, classification_output, selection)
    indicators = build_indicators_metrics_table(classification_output, selection)
    bias       = build_technical_bias_table(classification_output, selection)
    statistics = build_statistical_performance_table(classification_output, selection)
    tables     = {"indicator_package": {key: deepcopy(indicators[key]) for key in ("table_id", "selected_market", "selected_timeframe", "rows")},
                   "technical_bias": {key: deepcopy(bias[key]) for key in ("table_id", "selected_market", "rows")},
                   "statistical_performance": {key: deepcopy(statistics[key]) for key in ("table_id", "selected_market", "selected_timeframe", "rows", "metadata")}}
    metadata   = processing_output.get("metadata", {})
    updated_at = classification_output.get("updated_at") or processing_output.get("updated_at") or metadata.get("updated_at")
    contract   = {"family": "prices_ohlcv", "screen": "prices", "contract_type": "selected_view", "schema_version": "1.2.0",
                   "selection": {"market": market, "timeframe": timeframe}, "kpis": kpis, "widgets": widgets, "tables": tables,
                   "comparison": _selected_comparison(processing_output, classification_output, timeframe),
                   "quality": {}, "data_as_of": _selected_data_as_of(processing_output, market, timeframe), "updated_at": updated_at,
                   "data_mode": metadata.get("data_mode", "live"), "is_demo": bool(metadata.get("is_demo", False))}
    serializable = True
    try:
        json.dumps(contract, allow_nan=False)
    except (TypeError, ValueError):
        serializable = False
    contract["quality"] = _selected_view_quality(kpis=kpis, widgets=widgets, tables=tables, serializable=serializable)
    json.dumps(contract, allow_nan=False)
    return contract
