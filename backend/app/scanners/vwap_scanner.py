"""VWAP reclaim, rejection and distance."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.indicators import atr, vwap
from app.scanners.base import Scanner, Signal, SignalDirection


class VwapScanner(Scanner):
    """Intraday only: session-anchored VWAP crosses and stretch.

    Distance from VWAP is measured in ATR, not percent. A 1% move away from VWAP
    means something very different on a stock that ranges 0.5% a day than on one
    that ranges 4%, so a percent threshold would fire constantly on one and never
    on the other.
    """

    name = "vwap"
    min_bars = 30

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {"atr_length": 14, "stretch_atr": 2.0, "cross_lookback": 3}

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        if not isinstance(df.index, pd.DatetimeIndex):
            return self.neutral(
                symbol, "VWAP needs a DatetimeIndex; this looks like non-intraday data"
            )

        vwap_series = vwap(df, anchor="session")
        atr_series = atr(df, self.params["atr_length"])

        if pd.isna(vwap_series.iloc[-1]) or pd.isna(atr_series.iloc[-1]):
            return self.neutral(symbol, "VWAP or ATR not yet warmed up")

        close = float(df["close"].iloc[-1])
        vwap_now = float(vwap_series.iloc[-1])
        atr_now = float(atr_series.iloc[-1])

        if atr_now <= 0:
            return self.neutral(symbol, "zero ATR, cannot measure stretch")

        distance_atr = (close - vwap_now) / atr_now

        above = df["close"] > vwap_series
        lookback = self.params["cross_lookback"]
        window = above.iloc[-(lookback + 1) :]
        reclaimed = bool(window.iloc[-1] and not window.iloc[0])
        lost = bool(not window.iloc[-1] and window.iloc[0])

        metrics = {
            "close": close,
            "vwap": vwap_now,
            "atr": atr_now,
            "distance_atr": distance_atr,
            "distance_pct": (close - vwap_now) / vwap_now * 100.0,
        }

        if reclaimed:
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                0.7,
                f"reclaimed VWAP ({vwap_now:.2f}), now {distance_atr:.2f} ATR above",
                **metrics,
            )

        if lost:
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                0.7,
                f"lost VWAP ({vwap_now:.2f}), now {abs(distance_atr):.2f} ATR below",
                **metrics,
            )

        stretch = self.params["stretch_atr"]
        if distance_atr >= stretch:
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                0.4,
                f"stretched {distance_atr:.2f} ATR above VWAP: extended, mean-reversion risk",
                **metrics,
            )

        if distance_atr <= -stretch:
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                0.4,
                f"stretched {abs(distance_atr):.2f} ATR below VWAP: extended, "
                "bounce candidate",
                **metrics,
            )

        side = "above" if distance_atr > 0 else "below"
        return self.neutral(
            symbol,
            f"holding {side} VWAP at {abs(distance_atr):.2f} ATR, no cross",
            **metrics,
        )
