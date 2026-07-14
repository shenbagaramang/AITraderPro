"""Momentum indicators: RSI, MACD, rate of change."""

from __future__ import annotations

import pandas as pd

from app.indicators.base import validate_length, validate_series
from app.indicators.trend import ema, rma


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index. Matches Pine ``ta.rsi``.

    Gains and losses are smoothed with Wilder's RMA, not an EMA.
    """
    validate_length(length)
    series = validate_series(series, length + 1)

    delta = series.diff()
    gains = delta.clip(lower=0.0)
    losses = (-delta).clip(lower=0.0)

    # diff() puts a NaN at index 0; drop it so the RMA seed uses `length` real bars.
    avg_gain = rma(gains.iloc[1:], length)
    avg_loss = rma(losses.iloc[1:], length)

    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))

    # avg_loss == 0 means an unbroken run of up bars: RSI is 100 by definition.
    out = out.where(avg_loss != 0.0, 100.0)
    out = out.where(avg_gain != 0.0, 0.0)
    out[avg_gain.isna()] = float("nan")

    return out.reindex(series.index).rename(f"rsi_{length}")


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD line, signal line and histogram. Matches Pine ``ta.macd``.

    Returns a frame with ``macd``, ``signal`` and ``histogram`` columns.
    """
    validate_length(fast, "fast")
    validate_length(slow, "slow")
    validate_length(signal, "signal")
    if fast >= slow:
        raise ValueError(f"fast ({fast}) must be shorter than slow ({slow})")

    series = validate_series(series, slow)

    macd_line = ema(series, fast) - ema(series, slow)
    # The signal line is an EMA of the MACD line, which only exists from bar
    # `slow`, so the NaN head is dropped before smoothing.
    signal_line = ema(macd_line.dropna(), signal).reindex(series.index)

    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        },
        index=series.index,
    )


def roc(series: pd.Series, length: int = 9) -> pd.Series:
    """Rate of change, in percent. Matches Pine ``ta.roc``."""
    validate_length(length)
    series = validate_series(series, length + 1)
    return (series.diff(length) / series.shift(length) * 100.0).rename(f"roc_{length}")
