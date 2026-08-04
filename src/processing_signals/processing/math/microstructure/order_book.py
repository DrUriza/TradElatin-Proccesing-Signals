"""Pure order-book and cumulative-depth mathematics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .series_metrics import clean_zero


def consolidate_levels(levels: Sequence[Mapping[str, Any]], *, side: str) -> tuple[list[dict[str, float]], dict[str, int]]:
    if side not in {"bid", "ask"}:
        raise ValueError("side_must_be_bid_or_ask")
    quantities: dict[float, float] = {}
    zero_count = 0
    for level in levels:
        price, quantity = float(level["price"]), float(level["quantity"])
        if quantity == 0:
            zero_count += 1
            continue
        quantities[price] = quantities.get(price, 0.0) + quantity
    ordered = sorted(quantities, reverse=side == "bid")
    return ([{"price": price, "quantity": clean_zero(quantities[price])} for price in ordered],
            {"source_levels": len(levels), "active_levels": len(ordered), "zero_quantity_levels_excluded": zero_count,
             "duplicate_prices_consolidated": max(0, len(levels) - zero_count - len(ordered))})


def enrich_levels(levels: Sequence[Mapping[str, float]], *, side: str, mid_price: float) -> list[dict[str, float]]:
    cumulative_quantity = cumulative_notional = 0.0
    result = []
    for level in levels:
        price, quantity = float(level["price"]), float(level["quantity"])
        notional = price * quantity
        distance = 100 * ((mid_price - price) if side == "bid" else (price - mid_price)) / mid_price
        cumulative_quantity += quantity
        cumulative_notional += notional
        result.append({"price": price, "quantity_base": clean_zero(quantity), "notional_quote": clean_zero(notional),
                       "distance_percent": clean_zero(distance), "distance_bps": clean_zero(distance * 100),
                       "cumulative_quantity_base": clean_zero(cumulative_quantity),
                       "cumulative_notional_quote": clean_zero(cumulative_notional)})
    return result


def depth_metrics(bid: float, ask: float) -> dict[str, Any]:
    total, net = bid + ask, bid - ask
    if total == 0:
        return {"status": "unavailable", "reason": "zero_total_depth", "bid": clean_zero(bid), "ask": clean_zero(ask),
                "total": 0.0, "net": clean_zero(net), "bid_share_percent": None, "ask_share_percent": None,
                "imbalance_percent": None}
    return {"status": "available", "reason": None, "bid": clean_zero(bid), "ask": clean_zero(ask),
            "total": clean_zero(total), "net": clean_zero(net), "bid_share_percent": clean_zero(100 * bid / total),
            "ask_share_percent": clean_zero(100 * ask / total), "imbalance_percent": clean_zero(100 * net / total)}


def band_depth(bids: Sequence[Mapping[str, float]], asks: Sequence[Mapping[str, float]], *, minimum: float,
               maximum: float | None, include_minimum: bool = True) -> dict[str, Any]:
    def selected(level: Mapping[str, float]) -> bool:
        distance = level["distance_percent"]
        lower = distance >= minimum if include_minimum else distance > minimum
        return lower and (maximum is None or distance <= maximum)
    bid_levels, ask_levels = [level for level in bids if selected(level)], [level for level in asks if selected(level)]
    quantity = depth_metrics(sum(level["quantity_base"] for level in bid_levels), sum(level["quantity_base"] for level in ask_levels))
    notional = depth_metrics(sum(level["notional_quote"] for level in bid_levels), sum(level["notional_quote"] for level in ask_levels))
    return {"base_quantity": quantity, "quote_notional": notional,
            "bid": {"quantity_base": quantity["bid"], "notional_quote": notional["bid"], "level_count": len(bid_levels)},
            "ask": {"quantity_base": quantity["ask"], "notional_quote": notional["ask"], "level_count": len(ask_levels)}}


def simulate_market_impact(levels: Sequence[Mapping[str, float]], *, quantity_requested_base: float,
                           mid_price: float, side: str) -> dict[str, Any]:
    remaining, filled, notional, consumed = quantity_requested_base, 0.0, 0.0, 0
    for level in levels:
        take = min(remaining, level["quantity_base"])
        if take > 0:
            consumed += 1
            filled += take
            notional += take * level["price"]
            remaining -= take
        if remaining <= 1e-12:
            break
    vwap = None if filled == 0 else notional / filled
    complete = remaining <= 1e-12
    impact = None if not complete else 10_000 * ((vwap - mid_price) if side == "buy" else (mid_price - vwap)) / mid_price
    return {"status": "available" if complete else "partial", "reason": None if complete else "insufficient_visible_depth",
            "quantity_requested_base": quantity_requested_base, "quantity_filled_base": clean_zero(filled), "fully_filled": complete,
            "levels_consumed": consumed, "vwap": clean_zero(vwap) if complete else None, "impact_bps": clean_zero(impact),
            "partial_fill_vwap": None if complete else clean_zero(vwap)}


def process_order_book_levels(bid_levels: Sequence[Mapping[str, Any]], ask_levels: Sequence[Mapping[str, Any]], *,
                              impact_quantity: float = 1.0) -> dict[str, Any]:
    bids, bid_meta = consolidate_levels(bid_levels, side="bid")
    asks, ask_meta = consolidate_levels(ask_levels, side="ask")
    if not bids or not asks:
        return {"status": "unavailable", "reason": "empty_order_book"}
    best_bid, best_ask = bids[0]["price"], asks[0]["price"]
    if best_bid >= best_ask:
        return {"status": "invalid", "reason": "crossed_or_locked_order_book"}
    mid = (best_bid + best_ask) / 2
    enriched_bids, enriched_asks = enrich_levels(bids, side="bid", mid_price=mid), enrich_levels(asks, side="ask", mid_price=mid)
    buy = simulate_market_impact(enriched_asks, quantity_requested_base=impact_quantity, mid_price=mid, side="buy")
    sell = simulate_market_impact(enriched_bids, quantity_requested_base=impact_quantity, mid_price=mid, side="sell")
    impact_status = "available" if buy["fully_filled"] and sell["fully_filled"] else "partial"
    return {"status": "available", "reason": None, "best_bid": best_bid, "best_ask": best_ask, "mid_price": mid,
            "spread_quote": clean_zero(best_ask - best_bid), "spread_bps": clean_zero(10_000 * (best_ask - best_bid) / mid),
            "bid_levels": enriched_bids, "ask_levels": enriched_asks,
            "bands": {"zero_to_one": band_depth(enriched_bids, enriched_asks, minimum=0, maximum=1),
                      "one_to_five": band_depth(enriched_bids, enriched_asks, minimum=1, maximum=5, include_minimum=False),
                      "zero_to_ten_reference": band_depth(enriched_bids, enriched_asks, minimum=0, maximum=10),
                      "full_visible_book": band_depth(enriched_bids, enriched_asks, minimum=0, maximum=None)},
            "market_impact": {"status": impact_status, "reason": None if impact_status == "available" else "one_or_more_sides_unavailable",
                              "buy": buy, "sell": sell,
                              "worst_side_impact_bps": max(buy["impact_bps"], sell["impact_bps"]) if impact_status == "available" else None},
            "metadata": {"bids": {**bid_meta, "first_price": bids[0]["price"], "last_price": bids[-1]["price"]},
                         "asks": {**ask_meta, "first_price": asks[0]["price"], "last_price": asks[-1]["price"]}}}


def derive_cumulative_band(lower: Mapping[str, Any], upper: Mapping[str, Any], *, name: str) -> dict[str, Any]:
    fields = ("bids_usd", "asks_usd", "bids_quantity", "asks_quantity")
    differences = {field: float(upper[field]) - float(lower[field]) for field in fields}
    if any(value < 0 for value in differences.values()):
        return {"status": "invalid", "reason": "non_monotonic_cumulative_depth", "name": name}
    return {"status": "available", "reason": None, "name": name, **{field: clean_zero(value) for field, value in differences.items()}}
