from __future__ import annotations

import pandas as pd

from processing_signals.processing.math.indicators.market_structure.fibonacci_levels   import fibonacci_levels
from processing_signals.processing.math.indicators.market_structure.support_resistance import support_resistance
from processing_signals.processing.math.indicators.momentum.cci                        import cci
from processing_signals.processing.math.indicators.momentum.momentum                   import momentum
from processing_signals.processing.math.indicators.momentum.roc                        import roc
from processing_signals.processing.math.indicators.momentum.rsi                        import rsi
from processing_signals.processing.math.indicators.momentum.stochastic                 import stochastic
from processing_signals.processing.math.indicators.momentum.tsi                        import tsi
from processing_signals.processing.math.indicators.momentum.williams_r                 import williams_r
from processing_signals.processing.math.indicators.trend.adx                           import adx
from processing_signals.processing.math.indicators.trend.macd                          import macd
from processing_signals.processing.math.indicators.trend.moving_averages               import ema, sma, wma
from processing_signals.processing.math.indicators.volatility.atr                      import atr
from processing_signals.processing.math.indicators.volatility.bollinger_bands          import bollinger_bands
from processing_signals.processing.math.indicators.volatility.donchian                 import donchian
from processing_signals.processing.math.indicators.volatility.keltner                  import keltner
from processing_signals.processing.math.indicators.volume.obv                          import obv
from processing_signals.processing.math.indicators.volume.mfi                          import mfi
from processing_signals.processing.math.indicators.volume.vwap                         import vwap


class IndicatorEngine:
    """Compute technical indicators only for OHLC-compatible frames."""

    REQUIRED_OHLC = {"open", "high", "low", "close"}

    def is_ohlc_compatible(self, df: pd.DataFrame) -> bool:
        return self.REQUIRED_OHLC.issubset(set(df.columns))

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.is_ohlc_compatible(df):
            return pd.DataFrame(index=df.index)

        volume = df["volume"] if "volume" in df.columns else pd.Series(0, index=df.index)
        out    = pd.DataFrame(index=df.index)
        out["sma_20"] = sma(df["close"], 20)
        out["sma_50"] = sma(df["close"], 50)
        out["sma_100"] = sma(df["close"], 100)
        out["sma_200"] = sma(df["close"], 200)
        out["ema_20"] = ema(df["close"], 20)
        out["ema_50"] = ema(df["close"], 50)
        out["wma_20"] = wma(df["close"], 20)
        out = pd.concat([out, macd(df["close"])], axis=1)
        out = pd.concat([out, adx(df["high"], df["low"], df["close"], 14)], axis=1)
        out["rsi_14"] = rsi(df["close"], 14)
        out = pd.concat([out, stochastic(df["high"], df["low"], df["close"])], axis=1)
        out["roc_12"] = roc(df["close"], 12)
        out["mom_10"] = momentum(df["close"], 10)
        out["williams_r_14"] = williams_r(df["high"], df["low"], df["close"], 14)
        out["tsi"] = tsi(df["close"])
        out["cci_20"] = cci(df["high"], df["low"], df["close"], 20)
        out["atr_14"] = atr(df["high"], df["low"], df["close"], 14)
        out = pd.concat([out, bollinger_bands(df["close"], 20, 2.0)], axis=1)
        out = pd.concat([out, donchian(df["high"], df["low"], 20)], axis=1)
        out = pd.concat([out, keltner(df["high"], df["low"], df["close"], 20)], axis=1)
        out["vwap"] = vwap(df["high"], df["low"], df["close"], volume)
        out["mfi_14"] = mfi(df["high"], df["low"], df["close"], volume, 14)
        out["obv"] = obv(df["close"], volume)
        out = pd.concat([out, support_resistance(df["high"], df["low"], 20)], axis=1)
        out = pd.concat([out, fibonacci_levels(df["high"], df["low"], 100)], axis=1)
        return out


def compute_ohlcv_indicators(df: pd.DataFrame) -> pd.DataFrame:
    return IndicatorEngine().compute(df)
