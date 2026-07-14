"""Indicator layer.

Pure functions only. Every function in this package takes a pandas Series or an
OHLCV DataFrame and returns a Series/DataFrame. No database, no broker, no
network, no logging, no config. That constraint is what makes them trivially
unit-testable and safe to reuse from scanners, the backtester and the agents
without any of them disagreeing about what an "EMA" is.

Smoothing conventions deliberately match TradingView/Pine Script so that a
signal fired here reconciles with what you see on the chart:

- ``ema``   seeds with an SMA of the first ``length`` bars, then recurses
            (Pine ``ta.ema``)
- ``rma``   Wilder smoothing, seeded with an SMA (Pine ``ta.rma``)
- ``rsi``   built on ``rma``, not on a plain EMA (Pine ``ta.rsi``)
- ``adx``   Wilder-smoothed DI and DX (Pine ``ta.dmi``)
- ``stdev`` population standard deviation, ddof=0 (Pine ``ta.stdev``)
- ``ichimoku`` projects the cloud *forward* by the displacement
"""

from app.indicators.momentum import macd, roc, rsi
from app.indicators.strength import adx, ichimoku
from app.indicators.trend import ema, rma, sma, supertrend
from app.indicators.volatility import atr, bollinger_bands, true_range
from app.indicators.volume import obv, relative_volume, vwap

__all__ = [
    "adx",
    "atr",
    "bollinger_bands",
    "ema",
    "ichimoku",
    "macd",
    "obv",
    "relative_volume",
    "rma",
    "roc",
    "rsi",
    "sma",
    "supertrend",
    "true_range",
    "vwap",
]
