"""Volatility indicators: true range, ATR, Bollinger Bands."""

from __future__ import annotations

import pandas as pd

from app.indicators.base import validate_length, validate_ohlcv, validate_series


def true_range(df: pd.DataFrame) -> pd.Series:
    """max(high-low, |high-prev_close|, |low-prev_close|). Pine ``ta.tr``."""
    df = validate_ohlcv(df, 1)

    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1).rename("true_range")


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Average True Range, Wilder-smoothed. Matches Pine ``ta.atr``."""
    from app.indicators.trend import rma  # local import: trend imports atr

    validate_length(length)
    df = validate_ohlcv(df, length + 1)

    tr = true_range(df)
    # tr[0] has no previous close, so it is dropped before seeding the RMA.
    return rma(tr.iloc[1:], length).reindex(df.index).rename(f"atr_{length}")


def bollinger_bands(series: pd.Series, length: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands. Matches Pine ``ta.bb``.

    Pine's ``ta.stdev`` is the *population* standard deviation (ddof=0). pandas
    defaults to the sample stdev (ddof=1), which makes the bands measurably
    wider — so ddof is pinned explicitly here.

    Returns ``upper``, ``middle``, ``lower``, ``bandwidth`` and ``percent_b``.
    ``bandwidth`` is what a squeeze scanner watches; ``percent_b`` locates price
    within the channel (0 = lower band, 1 = upper band).
    """
    validate_length(length)
    if std_dev <= 0:
        raise ValueError("std_dev must be positive")
    series = validate_series(series, length)

    middle = series.rolling(window=length, min_periods=length).mean()
    deviation = series.rolling(window=length, min_periods=length).std(ddof=0)

    upper = middle + std_dev * deviation
    lower = middle - std_dev * deviation
    width = (upper - lower).replace(0.0, float("nan"))

    return pd.DataFrame(
        {
            "upper": upper,
            "middle": middle,
            "lower": lower,
            "bandwidth": (upper - lower) / middle * 100.0,
            "percent_b": (series - lower) / width,
        },
        index=series.index,
    )
