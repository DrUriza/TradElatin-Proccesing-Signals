from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .target_types import HMIWindowMode


@dataclass(frozen=True)
class RoutingRule:
    family_key: str
    module_key: str
    hmi_window_mode: HMIWindowMode
    preferred_output_shapes: tuple[str, ...]
    required_fields_by_shape: Mapping[str, tuple[str, ...]]


FAMILY_KEY_ALIASES: dict[str, str] = {
    "volume_orderflow": "volume_orderflow",
    "cvd_volume_orderflow": "volume_orderflow",
    "derivatives_open_interest": "derivatives_open_interest",
    "open_interest_and_funding": "derivatives_open_interest",
    "on_chain_miners": "on_chain_miners",
    "onchain_miners": "on_chain_miners",
}


ROUTING_RULES: dict[str, RoutingRule] = {
    "prices_ohlcv": RoutingRule(
        family_key="prices_ohlcv",
        module_key="prices_ohlcv",
        hmi_window_mode="candlestick_main",
        preferred_output_shapes=("candlestick", "time_series"),
        required_fields_by_shape={
            "candlestick": ("timestamp", "open", "high", "low", "close"),
            "time_series": ("timestamp", "value"),
        },
    ),
    "liquidity_microstructure": RoutingRule(
        family_key="liquidity_microstructure",
        module_key="liquidity_microstructure",
        hmi_window_mode="orderbook_depth",
        preferred_output_shapes=("orderbook", "bars", "time_series", "event_list"),
        required_fields_by_shape={
            "orderbook": tuple(),
            "bars": ("timestamp", "value"),
            "time_series": ("timestamp", "value"),
            "event_list": ("timestamp", "value"),
        },
    ),
    "volume_orderflow": RoutingRule(
        family_key="volume_orderflow",
        module_key="cvd_volume_orderflow",
        hmi_window_mode="multi_axis_time_series",
        preferred_output_shapes=("cvd_time_series", "cvd_candlestick_derived", "orderflow_features", "volume_features"),
        required_fields_by_shape={
            "cvd_time_series": ("timestamp", "value"),
            "cvd_candlestick_derived": ("timestamp", "value"),
            "orderflow_features": ("timestamp", "value"),
            "volume_features": ("timestamp", "value"),
        },
    ),
    "institutional_flows": RoutingRule(
        family_key="institutional_flows",
        module_key="institutional_flows",
        hmi_window_mode="flow_monitor",
        preferred_output_shapes=("time_series", "event_list", "bars", "candlestick_derived"),
        required_fields_by_shape={
            "time_series": ("timestamp", "value"),
            "event_list": ("timestamp", "value"),
            "bars": ("timestamp", "value"),
            "candlestick_derived": ("timestamp", "value"),
        },
    ),
    "liquidations": RoutingRule(
        family_key="liquidations",
        module_key="liquidations",
        hmi_window_mode="event_timeline",
        preferred_output_shapes=("event_list", "time_series", "bars", "candlestick_derived"),
        required_fields_by_shape={
            "event_list": ("timestamp", "value"),
            "time_series": ("timestamp", "value"),
            "bars": ("timestamp", "value"),
            "candlestick_derived": ("timestamp", "value"),
        },
    ),
    "derivatives_open_interest": RoutingRule(
        family_key="derivatives_open_interest",
        module_key="open_interest_and_funding",
        hmi_window_mode="multi_axis_time_series",
        preferred_output_shapes=("time_series", "candlestick_derived", "regimes"),
        required_fields_by_shape={
            "time_series": ("timestamp", "value"),
            "candlestick_derived": ("timestamp", "value"),
            "regimes": ("timestamp", "value"),
        },
    ),
    "sentiment_positioning": RoutingRule(
        family_key="sentiment_positioning",
        module_key="sentiment_positioning",
        hmi_window_mode="multi_axis_time_series",
        preferred_output_shapes=("time_series", "bars", "candlestick_derived"),
        required_fields_by_shape={
            "time_series": ("timestamp", "value"),
            "bars": ("timestamp", "value"),
            "candlestick_derived": ("timestamp", "value"),
        },
    ),
    "on_chain_miners": RoutingRule(
        family_key="on_chain_miners",
        module_key="onchain_miners",
        hmi_window_mode="flow_monitor",
        preferred_output_shapes=("time_series", "event_list", "bars", "regimes"),
        required_fields_by_shape={
            "time_series": ("timestamp", "value"),
            "event_list": ("timestamp", "value"),
            "bars": ("timestamp", "value"),
            "regimes": ("timestamp", "value"),
        },
    ),
    "options_volatility": RoutingRule(
        family_key="options_volatility",
        module_key="options_volatility",
        hmi_window_mode="volatility_surface",
        preferred_output_shapes=("heatmap", "time_series", "snapshot", "event_list"),
        required_fields_by_shape={
            "heatmap": ("timestamp", "value"),
            "time_series": ("timestamp", "value"),
            "snapshot": ("timestamp", "value"),
            "event_list": ("timestamp", "value"),
        },
    ),
}


def canonical_family_key(family_key: str) -> str:
    key = family_key.strip()
    if key in FAMILY_KEY_ALIASES:
        return FAMILY_KEY_ALIASES[key]
    return key


def get_rule_for_family(family_key: str) -> RoutingRule | None:
    canonical_key = canonical_family_key(family_key)
    return ROUTING_RULES.get(canonical_key)
