from __future__ import annotations

import numpy as np
import pandas as pd


def bollinger_bands(close: pd.Series, window: int = 20, std_mult: float = 2.0) -> pd.DataFrame:
    close     = pd.to_numeric(close, errors="coerce")
    middle    = close.rolling(window).mean()
    std       = close.rolling(window).std()
    upper     = middle + std_mult * std
    lower     = middle - std_mult * std
    bandwidth = (upper - lower) / middle.replace(0, np.nan)
    percent_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return pd.DataFrame({
        f"bb_middle_{window}": middle,
        f"bb_upper_{window}": upper,
        f"bb_lower_{window}": lower,
        f"bb_bandwidth_{window}": bandwidth,
        f"bb_percent_b_{window}": percent_b,
    })
