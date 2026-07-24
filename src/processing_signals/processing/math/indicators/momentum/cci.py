from __future__ import annotations

import pandas as pd


def cci(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20) -> pd.Series:
    typical = (pd.to_numeric(high, errors="coerce") + pd.to_numeric(low, errors="coerce") + pd.to_numeric(close, errors="coerce")) / 3
    mean    = typical.rolling(window).mean()
    mad     = typical.rolling(window).apply(lambda values: abs(values - values.mean()).mean(), raw=False)
    return (typical - mean) / (0.015 * mad.replace(0, pd.NA))
