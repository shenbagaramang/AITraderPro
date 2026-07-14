"""Trend-strength indicators: ADX/DI and Ichimoku."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators.base import validate_length, validate_ohlcv
from app.indicators.trend import rma
from app.indicators.volatility import true_range


def adx(df: pd.DataFrame, length: int = 14, smoothing: int | None = None) -> pd.DataFrame:
    """Average Directional Index with +DI and -DI. Matches Pine ``ta.dmi``.

    ADX measures trend *strength*, not direction — that is what +DI/-DI are for.
    The convention worth remembering: below 20 the market is ranging and every
    trend-following signal in the system is suspect; above 25 a trend is present.

    Returns ``adx``, ``plus_di`` and ``minus_di``.
    """
    validate_length(length)
    smoothing = smoothing if smoothing is not None else length
    validate_length(smoothing, "smoothing")
    df = validate_ohlcv(df, length + smoothing + 1)

    up_move = df["high"].diff()
    down_move = -df["low"].diff()

    # Only the larger of the two moves counts, and only if it is positive.
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
    )

    # Bar 0 has no previous close, so the true range there is meaningless.
    tr = true_range(df).iloc[1:]
    plus_dm = plus_dm.iloc[1:]
    minus_dm = minus_dm.iloc[1:]

    atr_series = rma(tr, length)
    safe_atr = atr_series.replace(0.0, np.nan)

    plus_di = 100.0 * rma(plus_dm, length) / safe_atr
    minus_di = 100.0 * rma(minus_dm, length) / safe_atr

    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum

    adx_series = rma(dx.dropna(), smoothing)

    return pd.DataFrame(
        {
            "adx": adx_series.reindex(df.index),
            "plus_di": plus_di.reindex(df.index),
            "minus_di": minus_di.reindex(df.index),
        },
        index=df.index,
    )


def ichimoku(
    df: pd.DataFrame,
    conversion: int = 9,
    base: int = 26,
    span_b: int = 52,
    displacement: int = 26,
) -> pd.DataFrame:
    """Ichimoku Kinko Hyo.

    The cloud (spans A and B) is projected *forward* by ``displacement`` bars, so
    the values sitting against today's price were computed 26 bars ago. That
    forward shift is the whole point of the indicator and is the thing most
    reimplementations get wrong — shifting the wrong way turns a leading
    indicator into a lagging one that looks uncannily accurate in backtest.

    ``cloud_top``/``cloud_bottom`` are the spans as they apply to the *current*
    bar, which is what a scanner actually wants to compare price against.

    Returns ``conversion``, ``base``, ``span_a``, ``span_b``, ``lagging``,
    ``cloud_top``, ``cloud_bottom``.
    """
    for name, value in (
        ("conversion", conversion),
        ("base", base),
        ("span_b", span_b),
        ("displacement", displacement),
    ):
        validate_length(value, name)
    df = validate_ohlcv(df, span_b + displacement)

    def midpoint(length: int) -> pd.Series:
        highest = df["high"].rolling(length, min_periods=length).max()
        lowest = df["low"].rolling(length, min_periods=length).min()
        return (highest + lowest) / 2.0

    conversion_line = midpoint(conversion)  # tenkan-sen
    base_line = midpoint(base)  # kijun-sen

    span_a = ((conversion_line + base_line) / 2.0).shift(displacement)  # senkou A
    span_b_line = midpoint(span_b).shift(displacement)  # senkou B
    lagging = df["close"].shift(-displacement)  # chikou

    return pd.DataFrame(
        {
            "conversion": conversion_line,
            "base": base_line,
            "span_a": span_a,
            "span_b": span_b_line,
            "lagging": lagging,
            "cloud_top": pd.concat([span_a, span_b_line], axis=1).max(axis=1),
            "cloud_bottom": pd.concat([span_a, span_b_line], axis=1).min(axis=1),
        },
        index=df.index,
    )
