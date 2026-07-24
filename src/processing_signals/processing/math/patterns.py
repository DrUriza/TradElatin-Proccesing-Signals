from __future__ import annotations

from copy import deepcopy
import math
from typing import Any, Mapping


DEFAULT_PATTERN_CONFIG = {"doji_body_ratio": 0.1, "small_body_ratio": 0.35, "shadow_body_multiple": 2.0}


def _candle(record: Mapping[str, Any]) -> dict[str, float]:
    opened, high, low, close = (float(record[key]) for key in ("open", "high", "low", "close"))
    span = high - low
    body = abs(close - opened)
    return {"open": opened, "high": high, "low": low, "close": close, "range": span,
            "body": body, "body_ratio": body / span if span > 0 else 0.0,
            "upper": high - max(opened, close), "lower": min(opened, close) - low}


def _event(record: Mapping[str, Any], pattern_id: str, direction: int, confidence: float, **components: float) -> dict[str, Any]:
    return {"timestamp": int(record["timestamp"]), "pattern_id": pattern_id, "direction": direction,
            "confidence": min(1.0, max(0.0, float(confidence))),
            "components": {key: float(value) for key, value in components.items() if math.isfinite(float(value))}}


def detect_candlestick_patterns(*, records: list[dict], config: dict | None = None) -> list[dict]:
    """Detect geometry-only candlestick patterns without semantic presentation."""
    cfg     = {**DEFAULT_PATTERN_CONFIG, **(config or {})}
    source  = sorted(deepcopy(records), key=lambda row: int(row["timestamp"]))
    candles = [_candle(row) for row in source]
    events: list[dict] = []
    for index, (record, candle) in enumerate(zip(source, candles, strict=True)):
        if candle["range"] <= 0:
            continue
        body_floor = max(candle["body"], candle["range"] * 0.01)
        if candle["body_ratio"] <= cfg["doji_body_ratio"]:
            events.append(_event(record, "doji", 0, 1 - candle["body_ratio"] / cfg["doji_body_ratio"], body_ratio=candle["body_ratio"]))
        small = candle["body_ratio"] <= cfg["small_body_ratio"]
        if small and candle["lower"] >= cfg["shadow_body_multiple"] * body_floor and candle["upper"] <= body_floor:
            events.append(_event(record, "hammer", 1, candle["lower"] / candle["range"], body_ratio=candle["body_ratio"], lower_shadow_ratio=candle["lower"] / candle["range"]))
        if small and candle["upper"] >= cfg["shadow_body_multiple"] * body_floor and candle["lower"] <= body_floor:
            pattern = "inverted_hammer" if candle["close"] >= candle["open"] else "shooting_star"
            events.append(_event(record, pattern, 1 if pattern == "inverted_hammer" else -1, candle["upper"] / candle["range"],
                                 body_ratio=candle["body_ratio"], upper_shadow_ratio=candle["upper"] / candle["range"]))
        if index >= 1:
            previous = candles[index - 1]
            bullish  = previous["close"] < previous["open"] and candle["close"] > candle["open"] and candle["open"] <= previous["close"] and candle["close"] >= previous["open"]
            bearish  = previous["close"] > previous["open"] and candle["close"] < candle["open"] and candle["open"] >= previous["close"] and candle["close"] <= previous["open"]
            if bullish or bearish:
                pattern    = "bullish_engulfing" if bullish else "bearish_engulfing"
                confidence = candle["body"] / max(previous["body"], candle["body"])
                events.append(_event(record, pattern, 1 if bullish else -1, confidence, body_ratio=candle["body_ratio"], previous_body_ratio=previous["body_ratio"]))
        if index >= 2:
            first, middle = candles[index - 2], candles[index - 1]
            midpoint = (first["open"] + first["close"]) / 2
            morning  = first["close"] < first["open"] and middle["body_ratio"] <= cfg["small_body_ratio"] and candle["close"] > candle["open"] and candle["close"] > midpoint
            evening  = first["close"] > first["open"] and middle["body_ratio"] <= cfg["small_body_ratio"] and candle["close"] < candle["open"] and candle["close"] < midpoint
            if morning or evening:
                events.append(_event(record, "morning_star" if morning else "evening_star", 1 if morning else -1,
                                     abs(candle["close"] - midpoint) / max(first["body"], 1e-12), middle_body_ratio=middle["body_ratio"]))
            trio  = candles[index - 2:index + 1]
            white = all(item["close"] > item["open"] for item in trio) and trio[0]["close"] < trio[1]["close"] < trio[2]["close"]
            black = all(item["close"] < item["open"] for item in trio) and trio[0]["close"] > trio[1]["close"] > trio[2]["close"]
            if white or black:
                events.append(_event(record, "three_white_soldiers" if white else "three_black_crows", 1 if white else -1,
                                     sum(item["body_ratio"] for item in trio) / 3,
                                     average_body_ratio=sum(item["body_ratio"] for item in trio) / 3))
    return sorted(events, key=lambda item: (item["timestamp"], item["pattern_id"]))
