from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_sum(df: pd.DataFrame, column: str) -> float:
    if df.empty or column not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[column], errors="coerce").fillna(0).sum())


def orderbook_metrics(bids: pd.DataFrame, asks: pd.DataFrame, top_levels: tuple[int, ...] = (5, 10, 20)) -> dict[str, float | None]:
    bids = bids.copy()
    asks = asks.copy()

    if bids.empty or asks.empty:
        return {}

    best_bid = float(bids["price"].iloc[0])
    best_ask = float(asks["price"].iloc[0])
    bid_qty_1 = float(bids["quantity_btc"].iloc[0])
    ask_qty_1 = float(asks["quantity_btc"].iloc[0])

    spread = best_ask - best_bid
    mid_price = (best_bid + best_ask) / 2
    weighted_mid_price = ((best_bid * ask_qty_1) + (best_ask * bid_qty_1)) / (bid_qty_1 + ask_qty_1) if (bid_qty_1 + ask_qty_1) else None

    total_bid_notional = _safe_sum(bids, "notional_usdt")
    total_ask_notional = _safe_sum(asks, "notional_usdt")
    total_depth = total_bid_notional + total_ask_notional
    imbalance = (total_bid_notional - total_ask_notional) / total_depth if total_depth else None

    metrics: dict[str, float | None] = {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread_usdt": spread,
        "spread_bps": (spread / mid_price) * 10000 if mid_price else None,
        "mid_price": mid_price,
        "weighted_mid_price": weighted_mid_price,
        "total_bid_notional_usdt": total_bid_notional,
        "total_ask_notional_usdt": total_ask_notional,
        "orderbook_imbalance_total": imbalance,
    }

    for n in top_levels:
        bid_n = _safe_sum(bids.head(n), "notional_usdt")
        ask_n = _safe_sum(asks.head(n), "notional_usdt")
        total_n = bid_n + ask_n
        metrics[f"bid_notional_top_{n}"] = bid_n
        metrics[f"ask_notional_top_{n}"] = ask_n
        metrics[f"depth_imbalance_top_{n}"] = (bid_n - ask_n) / total_n if total_n else None

    return metrics


def event_flow_metrics(events: pd.DataFrame, notional_column: str = "notional_usdt") -> dict[str, float | None]:
    if events.empty:
        return {}

    df = events.copy()
    if notional_column not in df.columns:
        df[notional_column] = 0
    if "quantity_btc" not in df.columns:
        df["quantity_btc"] = 0
    if "price" not in df.columns:
        df["price"] = np.nan

    df[notional_column] = pd.to_numeric(df[notional_column], errors="coerce").fillna(0)
    df["quantity_btc"] = pd.to_numeric(df["quantity_btc"], errors="coerce").fillna(0)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")

    buy = df[df["side"] == "buy"] if "side" in df.columns else df.iloc[0:0]
    sell = df[df["side"] == "sell"] if "side" in df.columns else df.iloc[0:0]

    buy_notional = float(buy[notional_column].sum())
    sell_notional = float(sell[notional_column].sum())
    total_notional = buy_notional + sell_notional
    imbalance = (buy_notional - sell_notional) / total_notional if total_notional else None

    def weighted_avg_price(x: pd.DataFrame) -> float | None:
        qty = x["quantity_btc"].sum()
        if qty == 0:
            return None
        return float((x["price"] * x["quantity_btc"]).sum() / qty)

    result: dict[str, float | None] = {
        "buy_count": int(len(buy)),
        "sell_count": int(len(sell)),
        "total_count": int(len(df)),
        "buy_notional_usdt": buy_notional,
        "sell_notional_usdt": sell_notional,
        "total_notional_usdt": total_notional,
        "flow_imbalance": imbalance,
        "buy_vwap": weighted_avg_price(buy),
        "sell_vwap": weighted_avg_price(sell),
    }

    if "age_seconds" in df.columns:
        age = pd.to_numeric(df["age_seconds"], errors="coerce").dropna()
        if not age.empty:
            result.update(
                {
                    "event_age_seconds_mean": float(age.mean()),
                    "event_age_seconds_max": float(age.max()),
                    "event_age_seconds_min": float(age.min()),
                }
            )

    if "active_duration_seconds" in df.columns:
        age = pd.to_numeric(df["active_duration_seconds"], errors="coerce").dropna()
        if not age.empty:
            result.update(
                {
                    "whale_order_age_seconds_mean": float(age.mean()),
                    "whale_order_age_seconds_max": float(age.max()),
                    "whale_order_age_seconds_min": float(age.min()),
                    "whale_order_age_minutes_mean": float(age.mean() / 60),
                    "whale_order_age_minutes_max": float(age.max() / 60),
                }
            )

    return result


def wall_score_from_orderbook(metrics: dict[str, float | None]) -> dict[str, float | None]:
    bid_top_10 = metrics.get("bid_notional_top_10") or 0
    ask_top_10 = metrics.get("ask_notional_top_10") or 0
    total = bid_top_10 + ask_top_10
    if total == 0:
        return {"bid_wall_score": None, "ask_wall_score": None}

    return {
        "bid_wall_score": bid_top_10 / total,
        "ask_wall_score": ask_top_10 / total,
    }
