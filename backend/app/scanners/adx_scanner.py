"""Trend strength via ADX/DI.

This scanner does double duty. Its *direction* comes from +DI vs -DI, but the
value the rest of the system really wants is ``metrics["adx"]`` — the regime
reading. The technical agent uses it to decide whether trend-following signals
should be trusted at all, which is why ADX is a scanner rather than something
the agent computes for itself.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.indicators import adx
from app.scanners.base import Scanner, Signal, SignalDirection


class AdxScanner(Scanner):
    name = "adx"
    min_bars = 60

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {"length": 14, "trending": 25.0, "ranging": 20.0}

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        frame = adx(df, self.params["length"])

        adx_now = frame["adx"].iloc[-1]
        plus = frame["plus_di"].iloc[-1]
        minus = frame["minus_di"].iloc[-1]

        if pd.isna(adx_now) or pd.isna(plus) or pd.isna(minus):
            return self.neutral(symbol, "ADX not yet warmed up")

        adx_now, plus, minus = float(adx_now), float(plus), float(minus)
        metrics = {"adx": adx_now, "plus_di": plus, "minus_di": minus}

        if adx_now < self.params["ranging"]:
            return self.neutral(
                symbol,
                f"ADX {adx_now:.1f}: no trend, market is ranging — "
                "trend-following signals are unreliable here",
                **metrics,
            )

        trending = adx_now >= self.params["trending"]
        # Strength scales from the ranging floor up to a saturation point of 50.
        magnitude = min((adx_now - self.params["ranging"]) / 30.0, 1.0)
        strength = 0.35 + 0.5 * magnitude

        if plus > minus:
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                strength,
                f"ADX {adx_now:.1f} ({'trending' if trending else 'building'}), "
                f"+DI {plus:.1f} over -DI {minus:.1f}",
                **metrics,
            )

        return self.signal(
            symbol,
            SignalDirection.BEARISH,
            strength,
            f"ADX {adx_now:.1f} ({'trending' if trending else 'building'}), "
            f"-DI {minus:.1f} over +DI {plus:.1f}",
            **metrics,
        )
