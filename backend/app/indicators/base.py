"""Shared validation helpers for the indicator layer."""

from __future__ import annotations

import pandas as pd

OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")


class IndicatorError(ValueError):
    """Raised when input data cannot support the requested indicator."""


def validate_length(length: int, name: str = "length") -> int:
    if not isinstance(length, int) or length < 1:
        raise IndicatorError(f"{name} must be a positive integer, got {length!r}")
    return length


def validate_series(series: pd.Series, length: int, name: str = "series") -> pd.Series:
    if not isinstance(series, pd.Series):
        raise IndicatorError(f"{name} must be a pandas Series, got {type(series).__name__}")
    if len(series) < length:
        raise IndicatorError(
            f"{name} has {len(series)} bars, need at least {length} for this indicator"
        )
    return series.astype("float64")


def validate_ohlcv(df: pd.DataFrame, length: int = 1) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame):
        raise IndicatorError(f"expected a DataFrame, got {type(df).__name__}")

    missing = [col for col in OHLCV_COLUMNS if col not in df.columns]
    if missing:
        raise IndicatorError(f"OHLCV frame is missing column(s): {', '.join(missing)}")
    if len(df) < length:
        raise IndicatorError(f"OHLCV frame has {len(df)} bars, need at least {length}")

    return df


def typical_price(df: pd.DataFrame) -> pd.Series:
    """HLC/3 — the price VWAP is conventionally computed against."""
    return (df["high"] + df["low"] + df["close"]) / 3.0
