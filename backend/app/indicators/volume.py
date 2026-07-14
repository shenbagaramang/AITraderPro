"""Volume indicators: session-anchored VWAP, relative volume, OBV."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.indicators.base import (
    IndicatorError,
    typical_price,
    validate_length,
    validate_ohlcv,
)


def vwap(df: pd.DataFrame, anchor: str = "session") -> pd.Series:
    """Volume Weighted Average Price.

    ``anchor="session"`` resets the accumulation at each new calendar day, which
    is what TradingView's intraday VWAP does and what any intraday strategy
    means by "VWAP". ``anchor="cumulative"`` never resets — appropriate only for
    anchored-VWAP-from-a-fixed-point use cases.

    Requires a DatetimeIndex when anchored to the session.
    """
    df = validate_ohlcv(df, 1)

    if anchor not in {"session", "cumulative"}:
        raise IndicatorError(f"anchor must be 'session' or 'cumulative', got {anchor!r}")

    tp = typical_price(df)
    pv = tp * df["volume"]

    if anchor == "cumulative":
        cum_pv = pv.cumsum()
        cum_vol = df["volume"].cumsum()
    else:
        if not isinstance(df.index, pd.DatetimeIndex):
            raise IndicatorError(
                "session-anchored VWAP needs a DatetimeIndex; "
                "pass anchor='cumulative' for undated data"
            )
        sessions = df.index.normalize()
        cum_pv = pv.groupby(sessions).cumsum()
        cum_vol = df["volume"].groupby(sessions).cumsum()

    return (cum_pv / cum_vol.replace(0, np.nan)).rename("vwap")


def relative_volume(df: pd.DataFrame, length: int = 20) -> pd.Series:
    """Current volume as a multiple of its own average. 2.0 = twice normal.

    The workhorse of confirmation: a breakout on 0.6x volume is noise, the same
    breakout on 3x volume is participation.
    """
    validate_length(length)
    df = validate_ohlcv(df, length)

    avg = df["volume"].rolling(window=length, min_periods=length).mean()
    return (df["volume"] / avg.replace(0, np.nan)).rename(f"rvol_{length}")


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume. Matches Pine ``ta.obv``."""
    df = validate_ohlcv(df, 2)

    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum().rename("obv")
