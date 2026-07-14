"""Ichimoku: price versus the cloud, plus the TK cross."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.indicators import ichimoku
from app.scanners.base import Scanner, Signal, SignalDirection


class IchimokuScanner(Scanner):
    """Grades the setup by how many Ichimoku conditions line up.

    The full bullish case is price above the cloud, conversion above base, and a
    green cloud ahead. Partial alignment is reported at proportionally lower
    strength rather than being rounded up to a signal.
    """

    name = "ichimoku"
    min_bars = 120

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {"conversion": 9, "base": 26, "span_b": 52, "displacement": 26}

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        frame = ichimoku(
            df,
            self.params["conversion"],
            self.params["base"],
            self.params["span_b"],
            self.params["displacement"],
        )
        row = frame.iloc[-1]

        needed = ("conversion", "base", "cloud_top", "cloud_bottom", "span_a", "span_b")
        if any(pd.isna(row[col]) for col in needed):
            return self.neutral(symbol, "Ichimoku cloud not yet formed")

        close = float(df["close"].iloc[-1])
        top, bottom = float(row["cloud_top"]), float(row["cloud_bottom"])

        metrics = {
            "close": close,
            "conversion": float(row["conversion"]),
            "base": float(row["base"]),
            "cloud_top": top,
            "cloud_bottom": bottom,
            "span_a": float(row["span_a"]),
            "span_b": float(row["span_b"]),
        }

        above_cloud = close > top
        below_cloud = close < bottom
        tk_bullish = row["conversion"] > row["base"]
        cloud_green = row["span_a"] > row["span_b"]

        if above_cloud:
            conditions = 1 + int(tk_bullish) + int(cloud_green)
            reasons = ["price above the cloud"]
            if tk_bullish:
                reasons.append("conversion over base")
            if cloud_green:
                reasons.append("cloud is green ahead")
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                0.3 + 0.2 * conditions,
                f"Ichimoku bullish ({conditions}/3): " + ", ".join(reasons),
                **metrics,
            )

        if below_cloud:
            conditions = 1 + int(not tk_bullish) + int(not cloud_green)
            reasons = ["price below the cloud"]
            if not tk_bullish:
                reasons.append("conversion under base")
            if not cloud_green:
                reasons.append("cloud is red ahead")
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                0.3 + 0.2 * conditions,
                f"Ichimoku bearish ({conditions}/3): " + ", ".join(reasons),
                **metrics,
            )

        return self.neutral(
            symbol,
            f"price inside the cloud ({bottom:.2f}–{top:.2f}): "
            "Ichimoku is undecided, which is itself information",
            **metrics,
        )
