"""EMA alignment and crossover."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.indicators import ema
from app.scanners.base import Scanner, Signal, SignalDirection


class EmaScanner(Scanner):
    """Fires when the fast EMA crosses the slow EMA, or when the stack is aligned.

    A fresh cross scores higher than a long-established trend: the cross is the
    event, the alignment is only context.
    """

    name = "ema"
    min_bars = 60

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {"fast": 9, "slow": 21, "trend": 50, "cross_lookback": 3}

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        fast_len = self.params["fast"]
        slow_len = self.params["slow"]
        trend_len = self.params["trend"]
        lookback = self.params["cross_lookback"]

        close = df["close"]
        fast = ema(close, fast_len)
        slow = ema(close, slow_len)
        trend = ema(close, trend_len)

        if pd.isna(fast.iloc[-1]) or pd.isna(slow.iloc[-1]) or pd.isna(trend.iloc[-1]):
            return self.neutral(symbol, "EMAs not yet warmed up")

        spread = fast - slow
        above = spread > 0
        price = float(close.iloc[-1])

        metrics = {
            f"ema_{fast_len}": float(fast.iloc[-1]),
            f"ema_{slow_len}": float(slow.iloc[-1]),
            f"ema_{trend_len}": float(trend.iloc[-1]),
            "spread_pct": float(spread.iloc[-1] / slow.iloc[-1] * 100.0),
            "close": price,
        }

        # A cross is a sign change in the spread within the lookback window.
        window = above.iloc[-(lookback + 1) :]
        crossed_up = bool(window.iloc[-1] and not window.iloc[0])
        crossed_down = bool(not window.iloc[-1] and window.iloc[0])

        above_trend = price > float(trend.iloc[-1])

        if crossed_up:
            # Confirmed by the longer trend, a cross is worth more.
            strength = 0.85 if above_trend else 0.55
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                strength,
                f"EMA{fast_len} crossed above EMA{slow_len}"
                + (f", price above EMA{trend_len}" if above_trend else ""),
                **metrics,
            )

        if crossed_down:
            strength = 0.85 if not above_trend else 0.55
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                strength,
                f"EMA{fast_len} crossed below EMA{slow_len}"
                + (f", price below EMA{trend_len}" if not above_trend else ""),
                **metrics,
            )

        # No cross: report standing alignment, but at a lower strength.
        if bool(above.iloc[-1]) and above_trend:
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                0.4,
                f"EMA stack aligned bullish ({fast_len} > {slow_len}, price > {trend_len})",
                **metrics,
            )

        if not bool(above.iloc[-1]) and not above_trend:
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                0.4,
                f"EMA stack aligned bearish ({fast_len} < {slow_len}, price < {trend_len})",
                **metrics,
            )

        return self.neutral(symbol, "EMAs mixed, no alignment or cross", **metrics)
