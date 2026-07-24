from __future__ import annotations

import pandas as pd


def tsi(close: pd.Series, slow: int = 25, fast: int = 13) -> pd.Series:
    close      = pd.to_numeric(close, errors="coerce")
    momentum   = close.diff()
    smooth     = momentum.ewm(span=slow, adjust=False).mean().ewm(span=fast, adjust=False).mean()
    abs_smooth = momentum.abs().ewm(span=slow, adjust=False).mean().ewm(span=fast, adjust=False).mean()
    return 100 * smooth / abs_smooth.replace(0, pd.NA)
