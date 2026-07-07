from __future__ import annotations

from typing import Any

import pandas as pd


EXCLUDED_REFERENCE_COLUMNS = {
    "time",
    "timestamp",
    "date",
    "datetime",
    "blockheight",
    "block_height",
    "unix",
    "epoch",
    "id",
    "index",
    "provider",
    "symbol",
    "asset",
    "exchange",
    "timeframe",
    "extraction_window",
}

SEMANTIC_REFERENCE_PRIORITY = [
    "close",
    "value",
    "cvd",
    "cum_vol_delta",
    "volume_delta",
    "taker_buy_volume",
    "taker_sell_volume",
    "taker_buy_vol",
    "taker_sell_vol",
    "buy_volume",
    "sell_volume",
    "open_interest",
    "open_interest_usd",
    "funding_rate",
    "basis",
    "estimated_leverage_ratio",
    "long_short_ratio",
    "account_long_short_ratio",
    "position_long_short_ratio",
    "global_account_long_short_ratio",
    "top_account_long_short_ratio",
    "top_position_long_short_ratio",
    "top_trader_long_short_ratio",
    "miner_reserve",
    "miner_inflow",
    "miner_outflow",
    "miner_outflow_multiple",
    "mpi",
    "hash_rate",
    "hashrate",
    "difficulty",
    "miner_revenue",
    "exchange_inflow",
    "exchange_outflow",
    "exchange_netflow",
    "exchange_reserve",
    "netflow",
    "inflow",
    "outflow",
    "reserve",
    "etf_flow",
    "etf_flows",
    "implied_volatility",
    "realized_volatility",
    "options_open_interest",
    "options_volume",
    "skew",
    "fear_greed",
    "sentiment_score",
]

SEMANTIC_SUBTYPE_ALIASES = {
    "cvd": ["cvd", "cum_vol_delta", "volume_delta"],
    "open_interest": ["open_interest", "open_interest_usd"],
    "funding_rate": ["funding_rate", "funding_rates"],
    "basis": ["basis"],
    "long_short_ratio": ["long_short_ratio", "account_long_short_ratio", "position_long_short_ratio"],
    "miner_reserve": ["miner_reserve"],
    "miner_inflow": ["miner_inflow"],
    "miner_outflow": ["miner_outflow"],
    "implied_volatility": ["implied_volatility", "value_1_month", "value_1_week", "value_3_month"],
    "implied_volatility_atm": ["implied_volatility", "value_1_month", "value_1_week", "value_3_month"],
    "realized_volatility": ["realized_volatility"],
    "options_open_interest": ["options_open_interest"],
    "options_volume": ["options_volume"],
}


def select_reference_column(
    df: pd.DataFrame,
    preferred: str | None = None,
    semantic_subtype: str | None = None,
    family: str | None = None,
) -> str | None:
    if preferred and is_valid_reference_column(df, preferred):
        return preferred

    subtype = normalize_column_name(semantic_subtype)
    for candidate in SEMANTIC_SUBTYPE_ALIASES.get(subtype, [subtype] if subtype else []):
        match = find_column(df, candidate)
        if match and is_valid_reference_column(df, match):
            return match

    for candidate in SEMANTIC_REFERENCE_PRIORITY:
        match = find_column(df, candidate)
        if match and is_valid_reference_column(df, match):
            return match

    for column in df.select_dtypes(include="number").columns:
        name = str(column)
        if is_valid_reference_column(df, name):
            return name
    return None


def reference_column(df: pd.DataFrame, preferred: str | None = None) -> str | None:
    return select_reference_column(df, preferred=preferred)


def time_series_to_bars(
    df: pd.DataFrame,
    preferred: str | None = None,
    semantic_subtype: str | None = None,
    family: str | None = None,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Create OHLC-compatible bar records from OHLC data or one numeric series."""
    if df.empty:
        return [], None, "no_valid_reference_column"

    ref = select_reference_column(
        df,
        preferred=preferred,
        semantic_subtype=semantic_subtype,
        family=family,
    )
    if not ref:
        return [], None, "no_valid_reference_column"
    if is_excluded_reference_column(ref):
        return [], None, "excluded_reference_column"

    has_ohlc = all(column in df.columns for column in ["open", "high", "low", "close"])
    bars: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record: dict[str, Any] = {"timestamp": row.get("timestamp")}
        if has_ohlc:
            record.update({key: row.get(key) for key in ["open", "high", "low", "close"]})
        elif ref:
            value = row.get(ref)
            record.update({"open": value, "high": value, "low": value, "close": value})
        else:
            continue
        if "volume" in df.columns:
            record["volume"] = row.get("volume")
        elif "notional_volume" in df.columns:
            record["volume"] = row.get("notional_volume")
        else:
            record["volume"] = None
        bars.append(record)
    warning = validate_bars(bars, ref)
    return bars, ref, warning


def find_column(df: pd.DataFrame, target: str | None) -> str | None:
    normalized_target = normalize_column_name(target)
    if not normalized_target:
        return None
    for column in df.columns:
        if normalize_column_name(str(column)) == normalized_target:
            return str(column)
    return None


def is_valid_reference_column(df: pd.DataFrame, column: str) -> bool:
    if column not in df.columns or is_excluded_reference_column(column):
        return False
    values = pd.to_numeric(df[column], errors="coerce")
    return not values.isna().all()


def is_excluded_reference_column(column: str | None) -> bool:
    normalized = normalize_column_name(column)
    if normalized in EXCLUDED_REFERENCE_COLUMNS:
        return True
    return any(token in normalized for token in ["timestamp", "datetime", "blockheight"])


def normalize_column_name(column: str | None) -> str:
    return str(column or "").strip().lower()


def validate_bars(bars: list[dict[str, Any]], reference: str | None) -> str | None:
    if not bars:
        return "no_valid_reference_column"
    if is_excluded_reference_column(reference):
        return "excluded_reference_column"
    for record in bars:
        values = [record.get(key) for key in ["open", "high", "low", "close"]]
        numeric_values = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
        if not numeric_values.empty and numeric_values.abs().max() > 1e12 and is_excluded_reference_column(reference):
            return "timestamp_like_ohlc_values"
    return None
