"""Trend indicators: SMA, EMA, Wilder's RMA, Supertrend."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators.base import validate_length, validate_ohlcv, validate_series
from app.indicators.volatility import atr


def sma(series: pd.Series, length: int = 20) -> pd.Series:
    """Simple moving average. Matches Pine ``ta.sma``."""
    validate_length(length)
    series = validate_series(series, length)
    return series.rolling(window=length, min_periods=length).mean()


def ema(series: pd.Series, length: int = 20) -> pd.Series:
    """Exponential moving average, seeded with an SMA. Matches Pine ``ta.ema``.

    pandas' ``ewm(adjust=False)`` alone starts the recursion from the *first*
    value, which drifts from TradingView for the first few dozen bars. Seeding
    with the SMA of the first ``length`` bars removes that discrepancy.
    """
    validate_length(length)
    series = validate_series(series, length)

    alpha = 2.0 / (length + 1.0)
    values = series.to_numpy(dtype="float64")
    out = np.full(values.shape, np.nan, dtype="float64")

    seed = values[:length].mean()
    out[length - 1] = seed
    for i in range(length, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]

    return pd.Series(out, index=series.index, name=f"ema_{length}")


def rma(series: pd.Series, length: int = 14) -> pd.Series:
    """Wilder's smoothing (alpha = 1/length). Matches Pine ``ta.rma``.

    This is what RSI and ATR are built on. Using a plain EMA here is the single
    most common reason a Python RSI disagrees with the one on the chart.
    """
    validate_length(length)
    series = validate_series(series, length)

    alpha = 1.0 / length
    values = series.to_numpy(dtype="float64")
    out = np.full(values.shape, np.nan, dtype="float64")

    out[length - 1] = values[:length].mean()
    for i in range(length, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]

    return pd.Series(out, index=series.index, name=f"rma_{length}")


def supertrend(df: pd.DataFrame, length: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """Supertrend line and direction (+1 uptrend, -1 downtrend).

    Returns a frame with ``supertrend`` and ``direction`` columns.
    """
    validate_length(length)
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    df = validate_ohlcv(df, length + 1)

    hl2 = (df["high"] + df["low"]) / 2.0
    atr_series = atr(df, length)

    upper = (hl2 + multiplier * atr_series).to_numpy()
    lower = (hl2 - multiplier * atr_series).to_numpy()
    close = df["close"].to_numpy(dtype="float64")

    n = len(df)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    trend = np.full(n, np.nan)

    start = int(np.argmax(~np.isnan(atr_series.to_numpy())))
    final_upper[start] = upper[start]
    final_lower[start] = lower[start]
    direction[start] = 1.0
    trend[start] = lower[start]

    for i in range(start + 1, n):
        final_upper[i] = (
            min(upper[i], final_upper[i - 1])
            if close[i - 1] <= final_upper[i - 1]
            else upper[i]
        )
        final_lower[i] = (
            max(lower[i], final_lower[i - 1])
            if close[i - 1] >= final_lower[i - 1]
            else lower[i]
        )

        if direction[i - 1] == 1.0:
            direction[i] = -1.0 if close[i] < final_lower[i] else 1.0
        else:
            direction[i] = 1.0 if close[i] > final_upper[i] else -1.0

        trend[i] = final_lower[i] if direction[i] == 1.0 else final_upper[i]

    return pd.DataFrame({"supertrend": trend, "direction": direction}, index=df.index)
