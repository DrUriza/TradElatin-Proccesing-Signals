from __future__ import annotations

from copy     import deepcopy
from datetime import UTC, datetime
import json
import math
from typing import Any, Mapping

from .prices_ohlcv_classifier import RSI_OVERBOUGHT, RSI_OVERSOLD, STOCHASTIC_OVERBOUGHT, STOCHASTIC_OVERSOLD


TIMEFRAME_ORDER        = ("1m", "5m", "15m", "1h", "4h", "1d")
MARKET_ORDER           = ("general", "spot", "futures")
DEFAULT_MARKET         = "general"
DEFAULT_TIMEFRAME      = "1h"
DEFAULT_DISPLAY_WINDOW = 120
TIMEFRAME_SECONDS      = {"1m": 60, "5m": 300, "15m": 900, "1h": 3_600, "4h": 14_400, "1d": 86_400}
TIMEFRAME_SOURCES      = {"1m": ("1m", 1), "5m": ("1m", 5), "15m": ("15m", 1), "1h": ("15m", 4), "4h": ("15m", 16), "1d": ("15m", 96)}

INDICATOR_ROWS = (
    ("rsi", "RSI (14)"), ("macd", "MACD"), ("macd_signal", "MACD Signal"), ("macd_histogram", "MACD Hist"),
    ("stochastic", "Stochastic (14,3,3)"), ("adx", "ADX (14)"), ("cci", "CCI (20)"), ("mfi", "MFI (14)"),
    ("williams_r", "Williams %R (14)"), ("atr", "ATR (14)"), ("tsi", "TSI (25,13)"),
)
STATISTICAL_ROWS = (
    ("mean", "Mean"), ("standard_deviation", "Std Dev"), ("skewness", "Skewness"), ("kurtosis", "Kurtosis"),
    ("z_score", "Z-Score"), ("var_95", "VaR (95%)"), ("cvar_95", "CVaR (95%)"),
    ("max_consecutive_wins", "Max Consec Wins"), ("max_consecutive_losses", "Max Consec Losses"),
    ("omega_ratio", "Omega Ratio"), ("sharpe_ratio", "Sharpe Ratio"), ("sortino_ratio", "Sortino Ratio"),
    ("calmar_ratio", "Calmar Ratio"), ("max_drawdown", "Max Drawdown"), ("profit_factor", "Profit Factor"),
    ("recovery_factor", "Recovery Factor"), ("win_rate", "Win Rate"),
)

INDICATOR_DISPLAY_FIELD = {
    "rsi": "state", "macd": "signal", "macd_signal": "signal", "macd_histogram": "signal", "stochastic": "state",
    "adx": "state", "cci": "signal", "mfi": "state", "williams_r": "state", "atr": "state", "tsi": "signal"}


def resolve_prices_selection(processing_output: Mapping[str, Any]) -> dict[str, Any]:
    selector             = processing_output.get("features", {}).get("market_selector", {})
    available_markets    = list(selector.get("available_markets") or MARKET_ORDER)
    available_timeframes = list(selector.get("timeframes") or TIMEFRAME_ORDER)
    selected_market      = selector.get("selected_market") or selector.get("default_market") or DEFAULT_MARKET
    selected_timeframe   = selector.get("selected_timeframe") or selector.get("default_timeframe") or DEFAULT_TIMEFRAME
    if selected_market not in available_markets:
        selected_market = available_markets[0] if available_markets else DEFAULT_MARKET
    if selected_timeframe not in available_timeframes:
        selected_timeframe = available_timeframes[0] if available_timeframes else DEFAULT_TIMEFRAME
    return {"selected_market": selected_market, "selected_timeframe": selected_timeframe,
            "available_markets": available_markets, "available_timeframes": available_timeframes}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_display_zero(value: Any, *, decimals: int) -> float | None:
    numeric = _finite(value)
    if numeric is None:
        return None
    rounded = round(numeric, decimals)
    return 0.0 if rounded == 0 else rounded


def _display(value: Any, *, percent: bool = False) -> str:
    numeric = _normalize_display_zero((_finite(value) or 0.0) * 100.0 if percent and _finite(value) is not None else value, decimals=2)
    if numeric is None:
        return "N/A"
    return f"{numeric:.2f}%" if percent else f"{numeric:.2f}"


def _display_signal(signal: str | None) -> str:
    return str(signal or "neutral").replace("_", " ").title()


def build_market_selector(processing_output: Mapping[str, Any], selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selection = dict(selection or resolve_prices_selection(processing_output))
    return {"selector_id": "prices_market", "selected": selection["selected_market"], "options": list(selection["available_markets"])}


def build_timeframe_selector(processing_output: Mapping[str, Any], selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selection = dict(selection or resolve_prices_selection(processing_output))
    return {"selector_id": "prices_timeframe", "selected": selection["selected_timeframe"], "options": list(selection["available_timeframes"])}


def _candle_metadata(*, timeframe: str, records: list[Mapping[str, Any]], reference_timestamp: int | None,
                     display_window: int = DEFAULT_DISPLAY_WINDOW) -> dict[str, Any]:
    last     = records[-1] if records else {}
    interval = TIMEFRAME_SECONDS[timeframe]
    canonical_source, canonical_expected = TIMEFRAME_SOURCES[timeframe]
    records_used = int(last.get("source_records", canonical_expected if last else 0))
    expected     = int(last.get("expected_source_records", canonical_expected))
    source       = str(last.get("source_timeframe", canonical_source))
    is_closed    = bool(last.get("is_closed", reference_timestamp is not None and int(last.get("timestamp", reference_timestamp)) + interval <= reference_timestamp))
    is_partial   = bool(last.get("is_partial", not is_closed))
    returned     = records[-display_window:]
    return {"reference_timestamp": reference_timestamp, "data_as_of": _timestamp_iso(last.get("timestamp")) if last else None,
            "timeframe": timeframe, "bar_interval_seconds": interval, "source_timeframe": source, "resampled": source != timeframe,
            "is_closed": is_closed, "is_partial": is_partial, "records_expected": expected, "records_used": records_used,
            "coverage_complete": bool(records and records_used >= expected and not is_partial),
            "records_available": len(records), "records_returned": len(returned), "display_window": display_window,
            "history_truncated": len(records) > len(returned), "first_available_timestamp": records[0].get("timestamp") if records else None,
            "last_available_timestamp": last.get("timestamp") if last else None, "first_returned_timestamp": returned[0].get("timestamp") if returned else None,
            "last_returned_timestamp": returned[-1].get("timestamp") if returned else None}


def _tail_series(series: Mapping[str, Any], limit: int) -> dict[str, Any]:
    return {name: (list(values[-limit:]) if limit else []) if isinstance(values, list) else deepcopy(values) for name, values in series.items()}


def _trim_indicator_package(package: Mapping[str, Any], limit: int) -> dict[str, Any]:
    output = deepcopy(dict(package))
    if isinstance(output.get("timestamps"), list):
        output["timestamps"] = output["timestamps"][-limit:] if limit else []
    if isinstance(output.get("series"), Mapping):
        output["series"] = _tail_series(output["series"], limit)
    return output


def _ohlcv_overlays(indicators: Mapping[str, Any], limit: int) -> dict[str, Any]:
    moving    = indicators.get("moving_averages", {})
    bands     = indicators.get("bollinger_bands", {})
    fibonacci = indicators.get("fibonacci_levels", {})
    overlays  = {
        "moving_averages": {"alignment": "ohlcv_records_by_index", "series": _tail_series(moving.get("series", {}), limit), "parameters": deepcopy(moving.get("parameters", {})),
                            "status": moving.get("quality", {}).get("status", "unavailable")},
        "bollinger_bands": {"alignment": "ohlcv_records_by_index", "series": _tail_series(bands.get("series", {}), limit), "parameters": deepcopy(bands.get("parameters", {})),
                            "status": bands.get("quality", {}).get("status", "unavailable")},
        "fibonacci_levels": {"render_mode": "horizontal_levels", "current": deepcopy(fibonacci.get("current", {})),
                             "parameters": deepcopy(fibonacci.get("parameters", {})), "status": fibonacci.get("quality", {}).get("status", "unavailable")},
    }
    for overlay_id in ("pivot_points", "support", "resistance", "vwap"):
        overlays[overlay_id] = {"status": "unavailable", "reason": "not_available_in_prices_processing"}
    return overlays


def _event_uid(event: Mapping[str, Any]) -> str:
    source = event.get("source", {})
    return f"{source.get('market')}:{source.get('timeframe')}:{event.get('timestamp')}:{event.get('event_type')}:{event.get('event_id')}"


def _processing_records(processing_output: Mapping[str, Any], market: str, timeframe: str) -> list[Mapping[str, Any]]:
    records = processing_output.get("markets", {}).get(market, {}).get("timeframes", {}).get(timeframe, {}).get("records", [])
    return records or processing_output.get("features", {}).get("main_ohlcv", {}).get(market, {}).get("timeframes", {}).get(timeframe, {}).get("records", [])


def _visible_timestamp_sets(processing_output: Mapping[str, Any], display_window: int = DEFAULT_DISPLAY_WINDOW) -> dict[str, dict[str, set[int]]]:
    return {market: {timeframe: {int(record["timestamp"]) for record in _processing_records(processing_output, market, timeframe)[-display_window:]}
                     for timeframe in TIMEFRAME_ORDER} for market in MARKET_ORDER}


def _event_registry(classification_output: Mapping[str, Any], processing_output: Mapping[str, Any]) -> dict[str, Any]:
    events   = classification_output.get("events", {})
    by_id    = {}
    type_ids = {"technical_cross_ids": [], "candlestick_pattern_ids": []}
    visible  = _visible_timestamp_sets(processing_output)
    for group, id_group in (("technical_crosses", "technical_cross_ids"), ("candlestick_patterns", "candlestick_pattern_ids")):
        for market in MARKET_ORDER:
            for timeframe in TIMEFRAME_ORDER:
                for event in events.get(group, {}).get(market, {}).get(timeframe, []):
                    if int(event.get("timestamp", -1)) not in visible[market][timeframe]:
                        continue
                    uid = _event_uid(event)
                    by_id[uid] = {"event_uid": uid, **deepcopy(event)}
                    if uid not in type_ids[id_group]:
                        type_ids[id_group].append(uid)
    return {"by_id": by_id, **type_ids}


def _chart_annotations(classification_output: Mapping[str, Any], processing_output: Mapping[str, Any]) -> dict[str, Any]:
    registry = _event_registry(classification_output, processing_output)
    output   = {}
    for market in MARKET_ORDER:
        output[market] = {}
        for timeframe in TIMEFRAME_ORDER:
            event_ids = [uid for uid, event in registry["by_id"].items()
                         if event.get("source", {}).get("market") == market and event.get("source", {}).get("timeframe") == timeframe]
            timestamps = sorted({registry["by_id"][uid].get("timestamp") for uid in event_ids})
            output[market][timeframe] = {"by_timestamp": {str(timestamp): [uid for uid in event_ids if registry["by_id"][uid].get("timestamp") == timestamp]
                                                                  for timestamp in timestamps}}
    return output


def build_main_ohlcv_chart(processing_output: Mapping[str, Any], classification_output: Mapping[str, Any] | None = None,
                           selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selection           = dict(selection or resolve_prices_selection(processing_output))
    markets             = deepcopy(processing_output.get("features", {}).get("main_ohlcv", {}))
    indicators          = processing_output.get("features", {}).get("indicators", {})
    reference_timestamp = processing_output.get("metadata", {}).get("reference_timestamp")
    for market in MARKET_ORDER:
        for timeframe in TIMEFRAME_ORDER:
            timeframe_data = markets.setdefault(market, {}).setdefault("timeframes", {}).setdefault(timeframe, {"records": [], "unavailable_records": []})
            full_records   = timeframe_data.get("records", [])
            timeframe_data["metadata"] = _candle_metadata(timeframe=timeframe, records=full_records, reference_timestamp=reference_timestamp)
            timeframe_data["records"]  = deepcopy(full_records[-DEFAULT_DISPLAY_WINDOW:])
            timeframe_data["overlays"] = _ohlcv_overlays(indicators.get(market, {}).get(timeframe, {}), len(timeframe_data["records"]))
    return {"chart_id": "prices_main_ohlcv", "selected_market": selection["selected_market"], "available_markets": list(selection["available_markets"]),
            "selected_timeframe": selection["selected_timeframe"], "available_timeframes": list(selection["available_timeframes"]), "markets": deepcopy(markets),
            "optional_overlays": {"spot_close": True, "futures_close": True, "general_close": True},
            "annotations": _chart_annotations(classification_output or {}, processing_output)}


def _indicator_chart(indicator_id: str, processing_output: Mapping[str, Any], selection: Mapping[str, Any],
                     thresholds: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    indicators = processing_output.get("features", {}).get("indicators", {})
    markets    = {market: {timeframe: _trim_indicator_package(indicators.get(market, {}).get(timeframe, {}).get(indicator_id, {}),
                                                                 min(DEFAULT_DISPLAY_WINDOW, len(_processing_records(processing_output, market, timeframe))))
                        for timeframe in TIMEFRAME_ORDER} for market in MARKET_ORDER}
    return {"chart_id": indicator_id, "selected_market": selection["selected_market"], "selected_timeframe": selection["selected_timeframe"],
            "available_markets": list(selection["available_markets"]), "available_timeframes": list(selection["available_timeframes"]), "markets": markets,
            "thresholds": thresholds or []}


def build_indicator_charts(processing_output: Mapping[str, Any], selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selection = dict(selection or resolve_prices_selection(processing_output))
    return {
        "rsi": _indicator_chart("rsi", processing_output, selection, [{"value": RSI_OVERBOUGHT, "role": "overbought"}, {"value": RSI_OVERSOLD, "role": "oversold"}]),
        "macd": _indicator_chart("macd", processing_output, selection), "stochastic": _indicator_chart("stochastic", processing_output, selection,
            [{"value": STOCHASTIC_OVERBOUGHT, "role": "overbought"}, {"value": STOCHASTIC_OVERSOLD, "role": "oversold"}]),
        "adx": _indicator_chart("adx", processing_output, selection), "cci": _indicator_chart("cci", processing_output, selection),
        "mfi": _indicator_chart("mfi", processing_output, selection), "williams_r": _indicator_chart("williams_r", processing_output, selection),
        "atr": _indicator_chart("atr", processing_output, selection), "tsi": _indicator_chart("tsi", processing_output, selection),
    }


def _indicator_row(metric_id: str, label: str, classification: Mapping[str, Any]) -> dict[str, Any]:
    value_fields  = {"macd": "macd", "macd_signal": "value", "macd_histogram": "value"}
    value         = classification.get(value_fields.get(metric_id, "value"))
    display_field = INDICATOR_DISPLAY_FIELD[metric_id]
    display_value = classification.get(display_field, "unavailable")
    parameters    = deepcopy(classification.get("parameters", {}))
    if metric_id == "tsi":
        parameters = {"long_period": parameters.get("long_period", parameters.get("slow_period")),
                      "short_period": parameters.get("short_period", parameters.get("fast_period"))}
    signal = classification.get("signal", "neutral")
    return {"metric_id": metric_id, "label": label, "value": _finite(value), "display_value": _display(value),
            "signal": signal, "signal_color_token": signal if signal in {"bullish", "bearish", "neutral", "positive", "negative"} else classification.get("color_token", "neutral"),
            "display_signal": _display_signal(display_value), "display_color_token": str(display_value or "neutral"),
            "state": classification.get("state", "unavailable"), "color_token": classification.get("color_token", "neutral"),
            "confidence": classification.get("confidence", 0.0), "parameters": parameters}


def build_indicators_metrics_table(classification_output: Mapping[str, Any], selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selection = dict(selection or {"selected_market": DEFAULT_MARKET, "selected_timeframe": DEFAULT_TIMEFRAME})
    source    = classification_output.get("indicator_signals", {})
    markets   = {market: {timeframe: [_indicator_row(metric_id, label, source.get(market, {}).get(timeframe, {}).get(metric_id, {}))
                                   for metric_id, label in INDICATOR_ROWS] for timeframe in TIMEFRAME_ORDER} for market in MARKET_ORDER}
    selected_market, selected_timeframe = selection["selected_market"], selection["selected_timeframe"]
    return {"table_id": "prices_indicator_package", "selected_market": selected_market, "selected_timeframe": selected_timeframe,
            "rows": deepcopy(markets[selected_market][selected_timeframe]), "markets": markets}


def build_technical_bias_table(classification_output: Mapping[str, Any], selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selection = dict(selection or {"selected_market": DEFAULT_MARKET})
    source    = classification_output.get("technical_bias", {})
    groups    = (("overall", "Overall Bias"), ("short", "Short (5m–15m)"), ("mid", "Mid (1h–4h)"), ("long", "Long (1d+)"))
    markets   = {market: [{"metric_id": group, "label": label, "score": _finite(source.get(market, {}).get(group, {}).get("score")),
                         "signal": source.get(market, {}).get(group, {}).get("label", "neutral"),
                         "display_signal": _display_signal(source.get(market, {}).get(group, {}).get("label")),
                         "confidence": _finite(source.get(market, {}).get(group, {}).get("confidence"))}
                        for group, label in groups] for market in MARKET_ORDER}
    selected_market = selection["selected_market"]
    return {"table_id": "prices_technical_bias", "selected_market": selected_market, "rows": deepcopy(markets[selected_market]), "markets": markets}


def _statistical_row(metric_id: str, label: str, classification: Mapping[str, Any]) -> dict[str, Any]:
    value    = classification.get("price_value") if metric_id in {"var_95", "cvar_95"} and classification.get("price_value") is not None else classification.get("value")
    percent  = metric_id in {"win_rate", "max_drawdown"}
    metadata = classification.get("metadata", {})
    is_dual  = metric_id in {"standard_deviation", "var_95", "cvar_95"}
    return {"metric_id": metric_id, "label": label, "value": _finite(value), "return_value": _finite(classification.get("return_value", classification.get("value"))) if is_dual else None,
            "unit": "quote_currency" if is_dual else ("decimal" if percent else "numeric"),
            "classification_unit": "decimal_return" if is_dual else None,
            "display_basis": metadata.get("display_basis", "price" if metric_id in {"var_95", "cvar_95"} else "close" if metric_id == "standard_deviation" else None),
            "classification_basis": metadata.get("classification_basis", "historical_simple_returns" if metric_id in {"var_95", "cvar_95"} else "simple_returns" if metric_id == "standard_deviation" else None),
            "confidence_level": 0.95 if metric_id in {"var_95", "cvar_95"} else None, "display_value": _display(value, percent=percent),
            "signal": classification.get("signal", "neutral"), "state": classification.get("state", "unavailable"),
            "display_signal": _display_signal(classification.get("state")), "display_color_token": classification.get("state", "neutral"),
            "signal_color_token": classification.get("signal", "neutral"), "color_token": classification.get("color_token", "neutral"),
            "metadata": deepcopy(metadata)}


def build_statistical_performance_table(classification_output: Mapping[str, Any], selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selection = dict(selection or {"selected_market": DEFAULT_MARKET, "selected_timeframe": DEFAULT_TIMEFRAME})
    source    = classification_output.get("statistical_signals", {})
    markets   = {market: {timeframe: [_statistical_row(metric_id, label, source.get(market, {}).get(timeframe, {}).get(metric_id, {}))
                                   for metric_id, label in STATISTICAL_ROWS] for timeframe in TIMEFRAME_ORDER} for market in MARKET_ORDER}
    selected_market, selected_timeframe = selection["selected_market"], selection["selected_timeframe"]
    metadata = source.get(selected_market, {}).get(selected_timeframe, {}).get("metadata", {})
    return {"table_id": "prices_statistical_performance", "selected_market": selected_market, "selected_timeframe": selected_timeframe,
            "rows": deepcopy(markets[selected_market][selected_timeframe]), "markets": markets, "metadata": deepcopy(metadata)}


def build_spot_futures_comparison_panel(processing_output: Mapping[str, Any], classification_output: Mapping[str, Any],
                                        selection: Mapping[str, Any] | None = None) -> dict[str, Any]:
    selection = dict(selection or resolve_prices_selection(processing_output))
    return {"panel_id": "spot_futures_general", "selected_market": selection["selected_market"], "selected_timeframe": selection["selected_timeframe"],
            "numeric": deepcopy(processing_output.get("features", {}).get("spot_futures_comparison", {})),
            "classification": deepcopy(classification_output.get("market_relationship", {}))}


def build_prices_events(classification_output: Mapping[str, Any], processing_output: Mapping[str, Any]) -> dict[str, Any]:
    return _event_registry(classification_output, processing_output)


def _kpi(metric_id: str, value: Any, *, unit: str, reason: str | None = None) -> dict[str, Any]:
    numeric = _finite(value)
    return {"metric_id": metric_id, "value": numeric, "unit": unit, "status": "available" if numeric is not None else "unavailable",
            **({"reason": reason or "insufficient_data"} if numeric is None else {})}


def _resolve_closed_24h_window(processing_output: Mapping[str, Any], market: str) -> dict[str, Any]:
    records       = processing_output.get("markets", {}).get(market, {}).get("timeframes", {}).get("1h", {}).get("records", [])
    closed        = [record for record in records if record.get("is_closed", True)]
    window        = closed[-24:]
    prior         = closed[-25] if len(closed) >= 25 else None
    current       = window[-1] if window else None
    volume_field  = "combined_volume_usd" if market == "general" else "volume_usd"
    current_close = _finite(current.get("close")) if current else None
    prior_close   = _finite(prior.get("close")) if prior else None
    volume_24h    = sum(float(record.get(volume_field, 0.0) or 0.0) for record in window) if len(window) == 24 else None
    return {"records": window, "records_used": len(window), "close_24h_ago": prior_close,
            "change_percent": ((current_close / prior_close) - 1.0) * 100.0 if current_close is not None and prior_close not in (None, 0.0) else None,
            "high": max((float(record["high"]) for record in window), default=None) if len(window) == 24 else None,
            "low": min((float(record["low"]) for record in window), default=None) if len(window) == 24 else None,
            "volume": volume_24h, "average_volume": volume_24h / 24.0 if volume_24h is not None else None, "volume_field": volume_field}


def build_prices_kpis(processing_output: Mapping[str, Any], selection: Mapping[str, Any]) -> dict[str, Any]:
    market     = selection["selected_market"]
    timeframe  = selection["selected_timeframe"]
    records    = processing_output.get("markets", {}).get(market, {}).get("timeframes", {}).get(timeframe, {}).get("records", [])
    indicators = processing_output.get("features", {}).get("indicators", {}).get(market, {}).get(timeframe, {})
    if not records:
        return {"selected_market": market, "selected_timeframe": timeframe,
                "items": [_kpi(metric_id, None, unit=unit) for metric_id, unit in (("last_price", "quote_currency"), ("high_24h", "quote_currency"),
                           ("low_24h", "quote_currency"), ("change_24h", "percent"), ("volume_24h", "quote_currency"),
                           ("market_cap", "quote_currency"), ("volatility_atr_percent", "percent"), ("average_range", "quote_currency"), ("beta", "ratio"))]}
    last          = records[-1]
    last_close    = _finite(last.get("close"))
    window_24h    = _resolve_closed_24h_window(processing_output, market)
    window        = window_24h["records"]
    atr           = _finite(indicators.get("atr", {}).get("current", {}).get("atr"))
    atr_percent   = atr / last_close * 100.0 if atr is not None and last_close not in (None, 0.0) else None
    average_range = sum(float(record["high"]) - float(record["low"]) for record in window) / len(window) if window else None
    items         = [_kpi("last_price", last_close, unit="quote_currency"), _kpi("high_24h", window_24h["high"], unit="quote_currency"),
             _kpi("low_24h", window_24h["low"], unit="quote_currency"), _kpi("change_24h", window_24h["change_percent"], unit="percent"),
             _kpi("volume_24h", window_24h["volume"], unit="quote_currency"),
             _kpi("market_cap", None, unit="quote_currency", reason="circulating_supply_not_available"),
             _kpi("volatility_atr_percent", atr_percent, unit="percent"), _kpi("average_range", average_range, unit="quote_currency"),
             _kpi("beta", None, unit="ratio", reason="benchmark_series_not_available")]
    return {"selected_market": market, "selected_timeframe": timeframe, "window_seconds": 86_400,
            "records_used_24h": window_24h["records_used"], "items": items}


def _timestamp_iso(timestamp: Any) -> str | None:
    numeric = _finite(timestamp)
    return datetime.fromtimestamp(numeric, tz=UTC).isoformat() if numeric is not None else None


def build_prices_operational_context(processing_output: Mapping[str, Any], selection: Mapping[str, Any]) -> dict[str, Any]:
    metadata    = processing_output.get("metadata", {})
    records     = processing_output.get("markets", {}).get(selection["selected_market"], {}).get("timeframes", {}).get(selection["selected_timeframe"], {}).get("records", [])
    data_as_of  = _timestamp_iso(records[-1].get("timestamp")) if records else None
    symbol      = metadata.get("symbol") or "BTCUSDT"
    quote_asset = metadata.get("quote_asset") or "USDT"
    base_asset  = symbol[:-len(quote_asset)] if isinstance(symbol, str) and symbol.endswith(quote_asset) else symbol
    return {"symbol": symbol, "base_asset": base_asset, "quote_asset": quote_asset, "exchange": metadata.get("exchange"),
            "provider": metadata.get("provider"), "units": {"price": quote_asset, "volume": f"{quote_asset}_notional", "returns": "decimal"},
            "refresh_policy": {"mode": processing_output.get("mode"), "contract": "atomic_file_replace"},
            "history_policy": {"calculation": "full_available_history", "presentation": "tail_window", "default_display_window": DEFAULT_DISPLAY_WINDOW},
            "data_mode": metadata.get("data_mode", "live"), "is_demo": bool(metadata.get("is_demo", False)),
            "reference_timestamp": metadata.get("reference_timestamp"), "generated_at": datetime.now(tz=UTC).isoformat(),
            "selected_data_as_of": data_as_of, "data_as_of": data_as_of, "updated_at": processing_output.get("updated_at")}


def _price_change_windows(records: list[Mapping[str, Any]], *, change_24h: float | None) -> dict[str, Any]:
    if not records:
        return {"1h": None, "4h": None, "24h": change_24h}
    current   = _finite(records[-1].get("close"))
    current_t = int(records[-1]["timestamp"])
    changes   = {}
    for window, seconds in (("1h", 3_600), ("4h", 14_400)):
        candidates = [record for record in records if int(record["timestamp"]) <= current_t - seconds]
        previous   = _finite(candidates[-1].get("close")) if candidates else None
        changes[window] = ((current / previous) - 1.0) * 100.0 if current is not None and previous not in (None, 0.0) else None
    changes["24h"] = change_24h
    return changes


def _unavailable_widget(widget_id: str, reason: str) -> dict[str, Any]:
    return {"widget_id": widget_id, "status": "unavailable", "reason": reason}


def build_prices_widgets(processing_output: Mapping[str, Any], classification_output: Mapping[str, Any], selection: Mapping[str, Any]) -> dict[str, Any]:
    market       = selection["selected_market"]
    timeframe    = selection["selected_timeframe"]
    records      = processing_output.get("markets", {}).get(market, {}).get("timeframes", {}).get(timeframe, {}).get("records", [])
    indicators   = processing_output.get("features", {}).get("indicators", {}).get(market, {}).get(timeframe, {})
    last         = deepcopy(records[-1]) if records else None
    window_24h   = _resolve_closed_24h_window(processing_output, market)
    window       = window_24h["records"]
    volume_key   = window_24h["volume_field"]
    volumes      = [_finite(record.get(volume_key)) for record in window]
    volumes      = [value for value in volumes if value is not None]
    registry     = _event_registry(classification_output, processing_output)
    pattern_rows = [uid for uid in registry["candlestick_pattern_ids"]
                     if registry["by_id"][uid].get("source", {}).get("market") == market and registry["by_id"][uid].get("source", {}).get("timeframe") == timeframe]
    averages   = indicators.get("moving_averages", {})
    statistics = classification_output.get("statistical_signals", {}).get(market, {}).get(timeframe, {})
    return {
        "price_change": {"widget_id": "price_change", "status": "available" if records else "unavailable", "unit": "percent",
                         "windows": _price_change_windows(records, change_24h=window_24h["change_percent"])},
        "moving_averages_summary": {"widget_id": "moving_averages_summary", "status": "available" if averages.get("current") else "unavailable",
                                    "values": deepcopy(averages.get("current", {})), "parameters": deepcopy(averages.get("parameters", {}))},
        "candlestick_patterns_analysis": {"widget_id": "candlestick_patterns_analysis", "status": "available", "row_ids": pattern_rows,
                                           "most_recent_id": pattern_rows[-1] if pattern_rows else None},
        "most_recent_candle": {"widget_id": "most_recent_candle", "status": "available" if last else "unavailable", "candle": last},
        "volume_analysis": {"widget_id": "volume_analysis", "status": "available" if volumes else "unavailable", "source_field": volume_key,
                            "current": volumes[-1] if volumes else None, "total_24h": window_24h["volume"],
                            "average_24h": window_24h["average_volume"], "records_used": window_24h["records_used"]},
        "drawdown": {"widget_id": "drawdown", "status": "available" if _finite(statistics.get("max_drawdown", {}).get("value")) is not None else "unavailable",
                     "value": _finite(statistics.get("max_drawdown", {}).get("value")), "unit": "decimal", "basis": "market_returns"},
        "range_price_behavior": {"widget_id": "range_price_behavior", "status": "available" if window else "unavailable",
                                 "current_range": (float(last["high"]) - float(last["low"])) if last else None,
                                 "average_range_24h": sum(float(record["high"]) - float(record["low"]) for record in window) / len(window) if window else None,
                                 "high_24h": max((float(record["high"]) for record in window), default=None),
                                 "low_24h": min((float(record["low"]) for record in window), default=None)},
        "volume_profile": _unavailable_widget("volume_profile", "price_volume_distribution_not_calculated"),
        "pivot_points_summary": _unavailable_widget("pivot_points_summary", "pivot_points_not_calculated"),
        "support_resistance_zones": _unavailable_widget("support_resistance_zones", "zones_not_calculated"),
        "distribution_histogram": _unavailable_widget("distribution_histogram", "histogram_bins_not_calculated"),
        "correlation": _unavailable_widget("correlation", "benchmark_series_not_available"),
        "price_forecast": _unavailable_widget("price_forecast", "forecast_model_not_configured"),
    }


def _contains_nonfinite(value: Any) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Mapping):
        return any(_contains_nonfinite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_nonfinite(item) for item in value)
    return False


def validate_prices_screen_coverage(contract: Mapping[str, Any], processing_output: Mapping[str, Any] | None = None,
                                    classification_output: Mapping[str, Any] | None = None) -> dict[str, Any]:
    missing = []
    charts  = contract.get("charts", {})
    tables  = contract.get("tables", {}).get("indicators_metrics", {})
    if len(charts) != 10:
        missing.append("charts.count")
    if len(tables.get("indicator_package", {}).get("rows", [])) != 11:
        missing.append("tables.indicator_package.rows")
    if len(tables.get("technical_bias", {}).get("rows", [])) != 4:
        missing.append("tables.technical_bias.rows")
    if len(tables.get("statistical_performance", {}).get("rows", [])) != len(STATISTICAL_ROWS):
        missing.append("tables.statistical_performance.rows")
    if contract.get("context", {}).get("performance_basis") != "market_returns":
        missing.append("context.performance_basis")
    if any(row.get("label") == "TSI (14)" for row in tables.get("indicator_package", {}).get("rows", [])):
        missing.append("tables.indicator_package.tsi_parameters")
    tsi_rows = [row for row in tables.get("indicator_package", {}).get("rows", []) if row.get("metric_id") == "tsi"]
    if not tsi_rows or tsi_rows[0].get("parameters") != {"long_period": 25, "short_period": 13}:
        missing.append("tables.indicator_package.tsi.parameters")
    if _contains_nonfinite(contract):
        missing.append("nonfinite_values")
    selection = {"market": contract.get("context", {}).get("default_market"), "timeframe": contract.get("context", {}).get("default_timeframe")}
    for chart in charts.values():
        if chart.get("selected_market") != selection["market"] or chart.get("selected_timeframe") != selection["timeframe"]:
            missing.append(f"charts.{chart.get('chart_id', 'unknown')}.selection")
    if classification_output is not None:
        indicators = classification_output.get("indicator_signals", {})
        statistics = classification_output.get("statistical_signals", {})
        biases     = classification_output.get("technical_bias", {})
        for market in contract.get("context", {}).get("available_markets", []):
            for timeframe in contract.get("context", {}).get("available_timeframes", []):
                for metric_id, _ in INDICATOR_ROWS:
                    if metric_id not in indicators.get(market, {}).get(timeframe, {}):
                        missing.append(f"classification.indicator_signals.{market}.{timeframe}.{metric_id}")
                for metric_id, _ in STATISTICAL_ROWS:
                    if metric_id not in statistics.get(market, {}).get(timeframe, {}):
                        missing.append(f"classification.statistical_signals.{market}.{timeframe}.{metric_id}")
            for group in ("overall", "short", "mid", "long"):
                if group not in biases.get(market, {}):
                    missing.append(f"classification.technical_bias.{market}.{group}")
    registered_events = contract.get("events", {}).get("by_id", {})
    if any(not event.get("source", {}).get("market") or not event.get("source", {}).get("timeframe") for event in registered_events.values()):
        missing.append("events.by_id.source")
    return {"status": "partial" if missing else "ok", "is_complete": not missing, "missing_fields": sorted(set(missing)), "warnings": [], "errors": []}


def _combine_prices_quality(*qualities: Mapping[str, Any]) -> dict[str, Any]:
    precedence     = {"ok": 0, "partial": 1, "invalid": 2}
    status         = max((str(quality.get("status", "ok")) for quality in qualities), key=lambda item: precedence.get(item, 2), default="ok")
    missing_fields = sorted({str(item) for quality in qualities for item in quality.get("missing_fields", [])})
    warnings       = [str(item) for quality in qualities for item in quality.get("warnings", [])]
    errors         = [str(item) for quality in qualities for item in quality.get("errors", [])]
    if errors:
        status = "invalid"
    elif missing_fields or warnings:
        status = "partial" if status != "invalid" else status
    return {"status": status, "is_complete": status == "ok", "missing_fields": missing_fields,
            "warnings": warnings, "errors": errors,
            "sources": {"processing": deepcopy(dict(qualities[0])), "classification": deepcopy(dict(qualities[1])),
                        "screen_coverage": deepcopy(dict(qualities[2])), "serialization": deepcopy(dict(qualities[3]))}}


def _screen_availability(contract: Mapping[str, Any]) -> dict[str, int]:
    kpis    = contract.get("kpis", {}).get("items", [])
    widgets = list(contract.get("widgets", {}).values())
    charts  = list(contract.get("charts", {}).values())
    tables  = list(contract.get("tables", {}).get("indicators_metrics", {}).values())
    return {"kpis_available": sum(item.get("status") == "available" for item in kpis), "kpis_total": len(kpis),
            "widgets_available": sum(item.get("status") == "available" for item in widgets), "widgets_total": len(widgets),
            "charts_available": len(charts), "charts_total": len(charts), "tables_available": len(tables), "tables_total": len(tables)}


def build_prices_screen_contract(processing_output: Mapping[str, Any], classification_output: Mapping[str, Any]) -> dict[str, Any]:
    if processing_output.get("family") != "prices_ohlcv" or classification_output.get("family") != "prices_ohlcv":
        raise ValueError("Prices screen contract requires prices_ohlcv inputs")
    if processing_output.get("stage") != "processing":
        raise ValueError("Prices screen contract requires stage=processing")
    if classification_output.get("stage") != "classification":
        raise ValueError("Prices screen contract requires stage=classification")
    selection = resolve_prices_selection(processing_output)
    charts    = {"ohlcv": build_main_ohlcv_chart(processing_output, classification_output, selection), **build_indicator_charts(processing_output, selection)}
    tables    = {"indicator_package": build_indicators_metrics_table(classification_output, selection),
                 "technical_bias": build_technical_bias_table(classification_output, selection),
                 "statistical_performance": build_statistical_performance_table(classification_output, selection)}
    performance_basis = classification_output.get("statistical_signals", {}).get(selection["selected_market"], {}).get(
        selection["selected_timeframe"], {}).get("metadata", {}).get("performance_basis")
    updated_at          = classification_output.get("updated_at") or processing_output.get("updated_at") or processing_output.get("metadata", {}).get("updated_at")
    operational_context = build_prices_operational_context(processing_output, selection)
    operational_context["updated_at"] = updated_at
    contract            = {"family": "prices_ohlcv", "screen": "prices", "schema_version": "1.2.0",
                "context": {"default_market": selection["selected_market"], "available_markets": list(selection["available_markets"]),
                            "default_timeframe": selection["selected_timeframe"], "available_timeframes": list(selection["available_timeframes"]),
                            "performance_basis": performance_basis, **operational_context},
                "badges": ([{"badge_id": "demo", "text": "DEMO"}] if operational_context["is_demo"] else []),
                "kpis": build_prices_kpis(processing_output, selection),
                "widgets": build_prices_widgets(processing_output, classification_output, selection),
                "selectors": {"market": build_market_selector(processing_output, selection), "timeframe": build_timeframe_selector(processing_output, selection)},
                "charts": charts, "tables": {"indicators_metrics": tables},
                "comparison": {"spot_futures_general": build_spot_futures_comparison_panel(processing_output, classification_output, selection)},
                "events": build_prices_events(classification_output, processing_output), "quality": {}}
    coverage_quality      = validate_prices_screen_coverage(contract, processing_output, classification_output)
    serialization_quality = {"status": "ok", "is_complete": True, "missing_fields": [], "warnings": [], "errors": []}
    try:
        json.dumps(contract, allow_nan=False)
    except (TypeError, ValueError) as exc:
        serialization_quality.update({"status": "invalid", "is_complete": False, "errors": [str(exc)]})
    contract["quality"] = _combine_prices_quality(processing_output.get("quality", {}), classification_output.get("quality", {}),
                                                  coverage_quality, serialization_quality)
    availability = _screen_availability(contract)
    contract["quality"].update({"contract_complete": coverage_quality["is_complete"] and serialization_quality["is_complete"],
                                "data_complete": availability["kpis_available"] == availability["kpis_total"] and availability["widgets_available"] == availability["widgets_total"],
                                "availability": availability, "presentation": {"window_limited": True, "default_display_window": DEFAULT_DISPLAY_WINDOW},
                                "compatibility_alias": {"is_complete": "contract_complete"}})
    contract["quality"]["is_complete"] = contract["quality"]["contract_complete"]
    json.dumps(contract, allow_nan=False)
    return contract
