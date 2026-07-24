from __future__ import annotations

import numpy as np
import pandas as pd

from processing_signals.processing.math.indicators.volatility.atr import true_range


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.DataFrame:
    high      = pd.to_numeric(high, errors="coerce")
    low       = pd.to_numeric(low, errors="coerce")
    close     = pd.to_numeric(close, errors="coerce")
    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm   = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm  = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    tr        = true_range(high, low, close).replace(0, np.nan)
    plus_di   = 100 * plus_dm.ewm(alpha=1 / window, min_periods=window, adjust=False).mean() / tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    minus_di  = 100 * minus_dm.ewm(alpha=1 / window, min_periods=window, adjust=False).mean() / tr.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    dx        = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    return pd.DataFrame({"adx_14": dx.ewm(alpha=1 / window, min_periods=window, adjust=False).mean(), "plus_di_14": plus_di, "minus_di_14": minus_di})
