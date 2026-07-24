from __future__ import annotations

import numpy as np
import pandas as pd


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    typical_price = (pd.to_numeric(high, errors="coerce") + pd.to_numeric(low, errors="coerce") + pd.to_numeric(close, errors="coerce")) / 3
    volume        = pd.to_numeric(volume, errors="coerce")
    return (typical_price * volume).cumsum() / volume.cumsum().replace(0, np.nan)
