from __future__ import annotations

import numpy as np
import pandas as pd


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    close     = pd.to_numeric(close, errors="coerce")
    volume    = pd.to_numeric(volume, errors="coerce").fillna(0)
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()
