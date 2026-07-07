from __future__ import annotations

from typing import Literal, TypeAlias

HMIWindowMode: TypeAlias = Literal[
    "candlestick_main",
    "multi_axis_time_series",
    "orderbook_depth",
    "event_timeline",
    "flow_monitor",
    "volatility_surface",
]

ValidationLevel: TypeAlias = Literal["error", "warning"]

DEFAULT_X_FIELD_CANDIDATES: tuple[str, ...] = ("timestamp", "time")
DEFAULT_Y_FIELD_PREFERRED: tuple[str, ...] = (
    "close",
    "value",
    "volume",
    "volume_usd",
    "open_interest",
    "funding_rate",
    "gamma_exposure",
)
