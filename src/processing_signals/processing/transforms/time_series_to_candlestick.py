from __future__ import annotations

from typing import Any

import pandas as pd

from processing_signals.processing.transforms.time_series_to_bars import time_series_to_bars


def time_series_to_candlestick(
    df: pd.DataFrame,
    preferred_reference: str | None = None,
    semantic_subtype: str | None = None,
    family: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create derived candles from a numeric time-series reference column."""
    candles, reference, warning = time_series_to_bars(
        df,
        preferred=preferred_reference,
        semantic_subtype=semantic_subtype,
        family=family,
    )
    return candles, {
        "method": "numeric_series_to_ohlc",
        "reference_column": reference,
        "warning": warning,
        "source_rows": int(len(df)),
        "derived_rows": len(candles),
    }
