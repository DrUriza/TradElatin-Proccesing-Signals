"""Pure enrichment and aggregation for executed trades."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from .series_metrics import clean_zero


def enrich_trade_event(event: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(event))
    result["quantity_base"] = clean_zero(float(event["volume_usd"]) / float(event["price"]))
    return result


def aggregate_trade_window(events: Sequence[Mapping[str, Any]], *, window_end: int, window_seconds: int) -> dict[str, Any]:
    selected = [event for event in events if window_end - window_seconds < event["timestamp"] <= window_end]
    buys = [event for event in selected if event["side"] == "buy"]
    sells = [event for event in selected if event["side"] == "sell"]
    buy_volume = sum(float(event["volume_usd"]) for event in buys)
    sell_volume = sum(float(event["volume_usd"]) for event in sells)
    total = buy_volume + sell_volume
    largest = max(selected, key=lambda event: float(event["volume_usd"]), default=None)
    return {"event_count": len(selected), "buy_count": len(buys), "sell_count": len(sells),
            "total_volume_usd": clean_zero(total), "buy_volume_usd": clean_zero(buy_volume),
            "sell_volume_usd": clean_zero(sell_volume), "net_flow_usd": clean_zero(buy_volume - sell_volume),
            "buy_share_percent": None if total == 0 else clean_zero(100 * buy_volume / total),
            "sell_share_percent": None if total == 0 else clean_zero(100 * sell_volume / total),
            "largest_event_id": largest.get("event_id") if largest else None,
            "largest_event_volume_usd": float(largest["volume_usd"]) if largest else None,
            "first_event_timestamp": min((event["timestamp"] for event in selected), default=None),
            "last_event_timestamp": max((event["timestamp"] for event in selected), default=None)}
