from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    close    = pd.to_numeric(close, errors="coerce")
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    result   = 100 - (100 / (1 + rs))
    # Wilder RSI is 100 when losses are zero, 0 when gains are zero, and 50
    # for an unchanged window. Preserve NaN during the configured warm-up.
    ready  = avg_gain.notna() & avg_loss.notna()
    result = result.mask(ready & avg_loss.eq(0) & avg_gain.gt(0), 100.0)
    result = result.mask(ready & avg_gain.eq(0) & avg_loss.gt(0), 0.0)
    return result.mask(ready & avg_gain.eq(0) & avg_loss.eq(0), 50.0)
