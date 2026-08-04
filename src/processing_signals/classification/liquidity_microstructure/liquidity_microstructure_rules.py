"""Pure threshold rules for Liquidity Classification v0.1."""

# ruff: noqa: E701, E702

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

CLASSIFICATION_VERSION      = "0.1"
CLASSIFICATION_RULE_VERSION = "liquidity_microstructure.rules.v0.1"
MARKETS                     = ("spot", "perpetual")
TIMEFRAMES                  = ("1m", "5m", "15m", "1h")
LARGE_TRADE_WINDOWS         = ("1m", "5m", "15m", "1h", "24h")

DEFAULT_THRESHOLDS = {
    "imbalance_balanced_max_abs_percent": 3.0, "imbalance_dominant_min_abs_percent": 10.0,
    "spread_tight_max_bps": 2.0, "spread_normal_max_bps": 5.0, "spread_wide_max_bps": 10.0,
    "impact_low_max_bps": 3.0, "impact_moderate_max_bps": 10.0, "impact_high_max_bps": 25.0,
    "large_trade_dominant_share_percent": 60.0, "whale_elevated_z_abs": 1.0, "whale_extreme_z_abs": 2.0,
    "market_return_flat_max_abs_percent": .25, "depth_ratio_spot_stronger_max": .80,
    "depth_ratio_perpetual_stronger_min": 1.25, "spread_comparable_max_abs_diff_bps": 1.0,
    "impact_comparable_max_abs_diff_bps": 2.0,
}


def validate_thresholds(config: Mapping[str, Any] | None) -> dict[str, float]:
    if config is not None and not isinstance(config, Mapping):
        raise ValueError("classification_config_must_be_mapping")
    thresholds = {**DEFAULT_THRESHOLDS, **dict((config or {}).get("thresholds", config or {}))}
    if set(thresholds) != set(DEFAULT_THRESHOLDS):
        raise ValueError("unknown_classification_threshold")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in thresholds.values()):
        raise ValueError("classification_threshold_must_be_finite_number")
    t = {key: float(value) for key, value in thresholds.items()}
    if not (0 <= t["imbalance_balanced_max_abs_percent"] < t["imbalance_dominant_min_abs_percent"] <= 100):
        raise ValueError("invalid_imbalance_thresholds")
    if not (0 <= t["spread_tight_max_bps"] <= t["spread_normal_max_bps"] <= t["spread_wide_max_bps"]):
        raise ValueError("invalid_spread_thresholds")
    if not (0 <= t["impact_low_max_bps"] <= t["impact_moderate_max_bps"] <= t["impact_high_max_bps"]):
        raise ValueError("invalid_impact_thresholds")
    if not (50 < t["large_trade_dominant_share_percent"] <= 100 and 0 < t["whale_elevated_z_abs"] < t["whale_extreme_z_abs"]):
        raise ValueError("invalid_flow_or_whale_thresholds")
    if not (0 < t["depth_ratio_spot_stronger_max"] < 1 < t["depth_ratio_perpetual_stronger_min"]):
        raise ValueError("invalid_depth_ratio_thresholds")
    return t


def atom(*, status: str, state: str, signal: str, signal_color: str, display: str, display_color: str,
         source_status: str = "available", source_timestamp: int | None = None, source_value: Any = None,
         source_values: Mapping[str, Any] | None = None, unit: str, parameters: Mapping[str, Any], reasons: list[str] | None = None) -> dict[str, Any]:
    result = {"status": status, "state": state, "signal": signal, "signal_color_token": signal_color,
              "display_signal": display, "display_color_token": display_color, "reason_codes": list(dict.fromkeys(reasons or [])),
              "provisional": status == "partial", "source_status": source_status, "source_timestamp": source_timestamp,
              "unit": unit, "parameters": dict(parameters)}
    result["source_values" if source_values is not None else "source_value"] = dict(source_values) if source_values is not None else source_value
    return result


def unavailable_atom(source_status: str, *, source_timestamp: int | None, unit: str, parameters: Mapping[str, Any], reason: str | None = None) -> dict[str, Any]:
    status = source_status if source_status in {"partial", "unavailable", "invalid"} else "unavailable"
    invalid = status == "invalid"
    return atom(status=status, state="invalid" if invalid else ("indeterminate" if status == "partial" else "unavailable"), signal="unavailable",
                signal_color="critical" if invalid else "unavailable", display="Unavailable",
                display_color="critical" if invalid else "muted", source_status=source_status, source_timestamp=source_timestamp,
                unit=unit, parameters=parameters, reasons=[reason or f"{status}_source"])


def classify_imbalance(value: float | None, *, source_status: str = "available", source_timestamp: int | None = None,
                       basis: str = "quote_notional", thresholds: Mapping[str, float] = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    params = {"basis": basis, "balanced_max_abs_percent": thresholds["imbalance_balanced_max_abs_percent"],
              "dominant_min_abs_percent": thresholds["imbalance_dominant_min_abs_percent"]}
    if value is None or source_status in {"unavailable", "invalid"}:
        return unavailable_atom(source_status, source_timestamp=source_timestamp, unit="percent", parameters=params)
    dominant, balanced = thresholds["imbalance_dominant_min_abs_percent"], thresholds["imbalance_balanced_max_abs_percent"]
    if value >= dominant: rule = ("bid_dominant", "bid_support", "positive", "Bid Dominant", "success")
    elif value >= balanced: rule = ("bid_leaning", "bid_support", "positive", "Bid Leaning", "success")
    elif value > -balanced: rule = ("balanced", "balanced_book", "neutral", "Balanced", "neutral")
    elif value > -dominant: rule = ("ask_leaning", "ask_pressure", "negative", "Ask Leaning", "danger")
    else: rule = ("ask_dominant", "ask_pressure", "negative", "Ask Dominant", "danger")
    return atom(status=source_status, state=rule[0], signal=rule[1], signal_color=rule[2], display=rule[3], display_color=rule[4],
                source_status=source_status, source_timestamp=source_timestamp, source_value=value, unit="percent", parameters=params,
                reasons=["partial_source"] if source_status == "partial" else [])


def classify_spread(value: float | None, *, source_status: str = "available", source_timestamp: int | None = None,
                    thresholds: Mapping[str, float] = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    params = {key: thresholds[key] for key in ("spread_tight_max_bps", "spread_normal_max_bps", "spread_wide_max_bps")}
    if value is None or source_status in {"unavailable", "invalid"}:
        return unavailable_atom(source_status, source_timestamp=source_timestamp, unit="bps", parameters=params)
    if value <= params["spread_tight_max_bps"]: rule = ("tight", "efficient_transaction_cost", "positive", "Tight", "success")
    elif value <= params["spread_normal_max_bps"]: rule = ("normal", "normal_transaction_cost", "neutral", "Normal", "neutral")
    elif value <= params["spread_wide_max_bps"]: rule = ("wide", "elevated_transaction_cost", "warning", "Wide", "warning")
    else: rule = ("stressed", "stressed_transaction_cost", "critical", "Stressed", "critical")
    return atom(status=source_status, state=rule[0], signal=rule[1], signal_color=rule[2], display=rule[3], display_color=rule[4],
                source_status=source_status, source_timestamp=source_timestamp, source_value=value, unit="bps", parameters=params)


def classify_impact(value: float | None, *, source_status: str = "available", source_timestamp: int | None = None,
                    fully_filled: bool = True, thresholds: Mapping[str, float] = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    params = {key: thresholds[key] for key in ("impact_low_max_bps", "impact_moderate_max_bps", "impact_high_max_bps")}
    if not fully_filled or value is None:
        return unavailable_atom("partial" if source_status != "invalid" else "invalid", source_timestamp=source_timestamp, unit="bps",
                                parameters=params, reason="incomplete_market_impact_fill")
    if source_status in {"unavailable", "invalid"}:
        return unavailable_atom(source_status, source_timestamp=source_timestamp, unit="bps", parameters=params)
    if value <= params["impact_low_max_bps"]: rule = ("low", "low_execution_cost", "positive", "Low", "success")
    elif value <= params["impact_moderate_max_bps"]: rule = ("moderate", "moderate_execution_cost", "neutral", "Moderate", "neutral")
    elif value <= params["impact_high_max_bps"]: rule = ("high", "high_execution_cost", "warning", "High", "warning")
    else: rule = ("severe", "severe_execution_cost", "critical", "Severe", "critical")
    return atom(status=source_status, state=rule[0], signal=rule[1], signal_color=rule[2], display=rule[3], display_color=rule[4],
                source_status=source_status, source_timestamp=source_timestamp, source_value=value, unit="bps", parameters=params)


def classify_trade_window(window: Mapping[str, Any], *, source_status: str, source_timestamp: int | None,
                          coverage_complete: bool, thresholds: Mapping[str, float] = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    count, buy, sell = window.get("event_count"), window.get("buy_share_percent"), window.get("sell_share_percent")
    params = {"dominant_share_percent": thresholds["large_trade_dominant_share_percent"]}
    if source_status == "invalid": return unavailable_atom("invalid", source_timestamp=source_timestamp, unit="percent", parameters=params)
    if count == 0: return atom(status=source_status, state="no_observations", signal="unavailable", signal_color="unavailable", display="No Observations",
                               display_color="muted", source_status=source_status, source_timestamp=source_timestamp,
                               source_values={"event_count": count, "buy_share_percent": buy, "sell_share_percent": sell}, unit="percent", parameters=params,
                               reasons=["stream_warmup_in_progress"] if source_status == "partial" else [])
    if buy is None or sell is None: return unavailable_atom(source_status, source_timestamp=source_timestamp, unit="percent", parameters=params)
    if buy >= params["dominant_share_percent"]: rule = ("buy_dominant", "buy_pressure", "positive", "Buy Dominant", "success")
    elif sell >= params["dominant_share_percent"]: rule = ("sell_dominant", "sell_pressure", "negative", "Sell Dominant", "danger")
    else: rule = ("balanced", "balanced_trade_flow", "neutral", "Balanced", "neutral")
    status = "partial" if source_status == "partial" or not coverage_complete else "available"
    return atom(status=status, state=rule[0], signal=rule[1], signal_color=rule[2], display=rule[3], display_color=rule[4],
                source_status=source_status, source_timestamp=source_timestamp,
                source_values={"event_count": count, "buy_share_percent": buy, "sell_share_percent": sell}, unit="percent", parameters=params,
                reasons=["incomplete_collection_window"] if not coverage_complete else [])


def classify_whale(value: float | None, *, source_status: str, source_timestamp: int | None,
                   reason: str | None = None, thresholds: Mapping[str, float] = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    params = {"elevated_z_abs": thresholds["whale_elevated_z_abs"], "extreme_z_abs": thresholds["whale_extreme_z_abs"]}
    if value is None or source_status in {"unavailable", "invalid"}:
        return unavailable_atom(source_status, source_timestamp=source_timestamp, unit="z_score", parameters=params, reason=reason)
    elevated, extreme = params["elevated_z_abs"], params["extreme_z_abs"]
    if value >= extreme: rule = ("extreme_positive_deviation", "unusual_positive_whale_activity", "positive", "Extreme Positive Deviation", "success")
    elif value >= elevated: rule = ("elevated_positive_deviation", "elevated_positive_whale_activity", "positive", "Elevated Positive Deviation", "success")
    elif value > -elevated: rule = ("normal_range", "normal_whale_activity", "neutral", "Normal Range", "neutral")
    elif value > -extreme: rule = ("elevated_negative_deviation", "elevated_negative_whale_activity", "negative", "Elevated Negative Deviation", "danger")
    else: rule = ("extreme_negative_deviation", "unusual_negative_whale_activity", "negative", "Extreme Negative Deviation", "danger")
    return atom(status=source_status, state=rule[0], signal=rule[1], signal_color=rule[2], display=rule[3], display_color=rule[4],
                source_status=source_status, source_timestamp=source_timestamp, source_value=value, unit="z_score", parameters=params)


def classify_market_change(value: float | None, *, source_status: str, source_timestamp: int | None,
                           thresholds: Mapping[str, float] = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    flat = thresholds["market_return_flat_max_abs_percent"]
    if value is None or source_status in {"unavailable", "invalid"}:
        return unavailable_atom(source_status, source_timestamp=source_timestamp, unit="percent", parameters={"flat_max_abs_percent": flat})
    if value >= flat: rule = ("rising", "positive_price_change", "positive", "Rising", "success")
    elif value <= -flat: rule = ("falling", "negative_price_change", "negative", "Falling", "danger")
    else: rule = ("flat", "flat_price_change", "neutral", "Flat", "neutral")
    return atom(status=source_status, state=rule[0], signal=rule[1], signal_color=rule[2], display=rule[3], display_color=rule[4],
                source_status=source_status, source_timestamp=source_timestamp, source_value=value, unit="percent",
                parameters={"flat_max_abs_percent": flat})


def classify_execution(spread: Mapping[str, Any], impact: Mapping[str, Any], *, source_timestamp: int | None) -> dict[str, Any]:
    if "invalid" in {spread["status"], impact["status"]}:
        return unavailable_atom("invalid", source_timestamp=source_timestamp, unit="semantic_state", parameters={"scope": "observed_transaction_cost_and_market_impact"})
    if spread["signal"] == "unavailable" or impact["signal"] == "unavailable":
        return unavailable_atom("partial", source_timestamp=source_timestamp, unit="semantic_state",
                                parameters={"scope": "observed_transaction_cost_and_market_impact"}, reason="insufficient_execution_liquidity_inputs")
    states = spread["state"], impact["state"]
    if states == ("tight", "low"): rule = ("robust", "strong_execution_liquidity", "positive", "Robust", "success")
    elif states[0] in {"tight", "normal"} and states[1] in {"low", "moderate"}: rule = ("healthy", "healthy_execution_liquidity", "positive", "Healthy", "success")
    elif states[0] == "stressed" or states[1] == "severe": rule = ("critical", "critical_execution_liquidity", "critical", "Critical", "critical")
    elif states[0] == "wide" or states[1] == "high": rule = ("constrained", "constrained_execution_liquidity", "warning", "Constrained", "warning")
    else: rule = ("mixed", "mixed_execution_liquidity", "neutral", "Mixed", "neutral")
    status = "partial" if "partial" in {spread["status"], impact["status"]} else "available"
    return atom(status=status, state=rule[0], signal=rule[1], signal_color=rule[2], display=rule[3], display_color=rule[4],
                source_status=status, source_timestamp=source_timestamp, source_values={"spread_state": states[0], "impact_state": states[1]},
                unit="semantic_state", parameters={"scope": "observed_transaction_cost_and_market_impact"})


def classify_comparison(value: float | None, *, kind: str, source_timestamp: int | None,
                        thresholds: Mapping[str, float] = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    if value is None:
        return unavailable_atom("unavailable", source_timestamp=source_timestamp, unit="ratio" if "depth" in kind else "bps", parameters={"kind": kind})
    if kind in {"depth_quote", "depth_base"}:
        low, high = thresholds["depth_ratio_spot_stronger_max"], thresholds["depth_ratio_perpetual_stronger_min"]
        state = "spot_deeper" if value <= low else ("perpetual_deeper" if value >= high else "comparable_depth")
        signal = state; unit = "ratio"
    else:
        limit = thresholds["spread_comparable_max_abs_diff_bps"] if kind == "spread" else thresholds["impact_comparable_max_abs_diff_bps"]
        if kind == "spread": state = "spot_tighter" if value >= limit else ("perpetual_tighter" if value <= -limit else "comparable_spread")
        elif kind == "buy_impact": state = "spot_lower_buy_impact" if value >= limit else ("perpetual_lower_buy_impact" if value <= -limit else "comparable_buy_impact")
        else: state = "spot_lower_sell_impact" if value >= limit else ("perpetual_lower_sell_impact" if value <= -limit else "comparable_sell_impact")
        signal = state; unit = "bps"
    color = "neutral" if state.startswith("comparable") else "warning"
    return atom(status="available", state=state, signal=signal, signal_color=color, display=state.replace("_", " ").title(),
                display_color=color, source_timestamp=source_timestamp, source_value=value, unit=unit, parameters={"kind": kind})


def classify_pressure_alignment(book_state: str, trade_state: str, *, source_timestamp: int | None) -> dict[str, Any]:
    bid, ask = book_state in {"bid_leaning", "bid_dominant"}, book_state in {"ask_leaning", "ask_dominant"}
    if trade_state == "no_observations": rule = ("indeterminate", "unavailable", "unavailable", "Unavailable", "muted")
    elif book_state == "balanced" or trade_state == "balanced": rule = ("mixed", "mixed_book_trade_pressure", "neutral", "Mixed", "neutral")
    elif bid and trade_state == "buy_dominant": rule = ("aligned_buy_side", "book_and_trades_buy_alignment", "positive", "Aligned Buy Side", "success")
    elif ask and trade_state == "sell_dominant": rule = ("aligned_sell_side", "book_and_trades_sell_alignment", "negative", "Aligned Sell Side", "danger")
    elif (bid and trade_state == "sell_dominant") or (ask and trade_state == "buy_dominant"): rule = ("divergent", "book_trade_divergence", "warning", "Divergent", "warning")
    else: rule = ("indeterminate", "unavailable", "unavailable", "Unavailable", "muted")
    return atom(status="available" if rule[0] != "indeterminate" else "partial", state=rule[0], signal=rule[1], signal_color=rule[2],
                display=rule[3], display_color=rule[4], source_timestamp=source_timestamp,
                source_values={"orderbook_balance_state": book_state, "large_trade_state": trade_state}, unit="semantic_state", parameters={})


def classify_cross_market_execution(spot_state: str, perpetual_state: str, *, source_timestamp: int | None) -> dict[str, Any]:
    states = {spot_state, perpetual_state}
    if "indeterminate" in states or "unavailable" in states:
        return unavailable_atom("partial", source_timestamp=source_timestamp, unit="semantic_state",
                                parameters={"scope": "coinglass_spot_perpetual_observed_execution_conditions"})
    if spot_state == perpetual_state == "robust": state = "robust"
    elif states <= {"robust", "healthy"}: state = "healthy"
    elif spot_state == perpetual_state == "critical": state = "critical"
    elif "critical" in states: state = "stressed"
    elif "constrained" in states: state = "constrained"
    else: state = "mixed"
    signal = f"cross_market_{state}_execution_liquidity"
    color = "positive" if state in {"robust", "healthy"} else ("critical" if state in {"critical", "stressed"} else "warning" if state == "constrained" else "neutral")
    display_color = "success" if color == "positive" else color
    return atom(status="available", state=state, signal=signal, signal_color=color, display=state.title(), display_color=display_color,
                source_timestamp=source_timestamp, source_values={"spot": spot_state, "perpetual": perpetual_state}, unit="semantic_state",
                parameters={"scope": "coinglass_spot_perpetual_observed_execution_conditions"})
