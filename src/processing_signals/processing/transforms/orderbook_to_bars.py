from __future__ import annotations

from typing import Any

import pandas as pd

from processing_signals.processing.transforms.time_series_to_bars import time_series_to_bars


def orderbook_to_bars(df: pd.DataFrame) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Create OHLC-compatible bars from orderbook snapshot metrics when available."""
    preferred = "mid_price" if "mid_price" in df.columns else None
    return time_series_to_bars(df, preferred=preferred, semantic_subtype="market_depth", family="liquidity_microstructure")
