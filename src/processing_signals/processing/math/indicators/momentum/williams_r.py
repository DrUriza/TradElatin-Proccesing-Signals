from __future__ import annotations

import pandas as pd


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    high    = pd.to_numeric(high, errors="coerce")
    low     = pd.to_numeric(low, errors="coerce")
    close   = pd.to_numeric(close, errors="coerce")
    highest = high.rolling(window).max()
    lowest  = low.rolling(window).min()
    return -100 * (highest - close) / (highest - lowest).replace(0, pd.NA)
