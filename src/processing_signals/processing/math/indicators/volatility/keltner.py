from __future__ import annotations

import pandas as pd

from processing_signals.processing.math.indicators.trend.moving_averages import ema
from processing_signals.processing.math.indicators.volatility.atr        import atr


def keltner(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 20, atr_mult: float = 2.0) -> pd.DataFrame:
    middle             = ema(close, window)
    average_true_range = atr(high, low, close, window)
    return pd.DataFrame({
        "keltner_middle_20": middle,
        "keltner_upper_20": middle + atr_mult * average_true_range,
        "keltner_lower_20": middle - atr_mult * average_true_range,
    })
