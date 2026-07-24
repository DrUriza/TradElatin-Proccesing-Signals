from __future__ import annotations

import pandas as pd


def support_resistance(high: pd.Series, low: pd.Series, window: int = 20) -> pd.DataFrame:
    support    = pd.to_numeric(low, errors="coerce").rolling(window).min()
    resistance = pd.to_numeric(high, errors="coerce").rolling(window).max()
    return pd.DataFrame({"support_20": support, "resistance_20": resistance})
