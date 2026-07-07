from __future__ import annotations


STRUCTURAL_DATA_TYPES = {
    "time_series",
    "candlestick",
    "orderbook",
    "event_list",
    "snapshot",
    "matrix",
    "heatmap",
}

SPECIAL_STRUCTURAL_DATA_TYPES = {"snapshot", "matrix", "heatmap"}

HMI_MODE_BY_FAMILY = {
    "prices_ohlcv": "timeframe_window",
    "liquidity_microstructure": "fixed_window",
    "cvd_volume_orderflow": "timeframe_window",
    "institutional_flows": "fixed_window",
    "liquidations": "fixed_window",
    "open_interest_and_funding": "timeframe_window",
    "sentiment_positioning": "timeframe_window",
    "onchain_miners": "fixed_window",
    "options_volatility": "timeframe_window",
}

PRIMARY_VIEW_TYPES = {
    "candlestick": "candlestick",
    "time_series": "time_series",
    "orderbook": "depth",
    "event_list": "events",
    "matrix": "matrix",
    "heatmap": "heatmap",
    "snapshot": "snapshot",
}


def hmi_mode_for(official_family: str) -> str:
    return HMI_MODE_BY_FAMILY.get(official_family, "timeframe_window")


def primary_view_type_for(structural_data_type: str) -> str:
    return PRIMARY_VIEW_TYPES.get(structural_data_type, "time_series")


def required_views_for(
    official_family: str,
    semantic_subtype: str,
    structural_data_type: str,
    hmi_mode: str,
) -> list[str]:
    if structural_data_type in SPECIAL_STRUCTURAL_DATA_TYPES:
        return [structural_data_type]

    semantic = semantic_subtype.lower()
    if structural_data_type == "candlestick":
        return ["candlestick", "time_series", "bars"]
    if structural_data_type == "orderbook":
        return ["depth"]
    if structural_data_type == "event_list":
        return ["event_list"]

    views = ["time_series"]
    if official_family in {
        "prices_ohlcv",
        "cvd_volume_orderflow",
        "open_interest_and_funding",
        "sentiment_positioning",
        "institutional_flows",
        "onchain_miners",
        "options_volatility",
    }:
        views.append("bars")
    if semantic in {"cvd", "open_interest", "funding_rate", "basis", "realized_volatility", "implied_volatility"}:
        views.append("candlestick_derived")
    if "liquidation" in semantic and hmi_mode == "timeframe_window":
        views.append("event_list")
    return views
