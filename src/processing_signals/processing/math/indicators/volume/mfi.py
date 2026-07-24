from __future__ import annotations

import numpy as np
import pandas as pd


def mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int = 14,
) -> pd.Series:
    high   = pd.to_numeric(high, errors="coerce")
    low    = pd.to_numeric(low, errors="coerce")
    close  = pd.to_numeric(close, errors="coerce")
    volume = pd.to_numeric(volume, errors="coerce").fillna(0)

    typical_price  = (high + low + close) / 3
    raw_money_flow = typical_price * volume
    direction      = typical_price.diff()
    positive_flow  = raw_money_flow.where(direction > 0, 0.0)
    negative_flow  = raw_money_flow.where(direction < 0, 0.0).abs()
    positive_sum   = positive_flow.rolling(window=window, min_periods=window).sum()
    negative_sum   = negative_flow.rolling(window=window, min_periods=window).sum()
    money_ratio    = positive_sum / negative_sum.replace(0, np.nan)
    return 100 - (100 / (1 + money_ratio))
