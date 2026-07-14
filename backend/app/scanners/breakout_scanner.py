"""Range breakout with volume and ATR confirmation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.indicators import atr, relative_volume
from app.scanners.base import Scanner, Signal, SignalDirection


class BreakoutScanner(Scanner):
    """Close beyond the prior N-bar range, confirmed by volume and range size.

    Two filters do most of the work here:

    - **Volume.** A breakout without participation is the single most common
      false positive. Below ``min_rvol`` the break is reported but heavily
      discounted, not celebrated.
    - **ATR.** The break must clear the level by a fraction of ATR, so a tick
      through a level on a doji does not count as a breakout.
    """

    name = "breakout"
    min_bars = 60

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {
            "lookback": 20,
            "atr_length": 14,
            "min_atr_buffer": 0.25,
            "min_rvol": 1.5,
            "vol_length": 20,
        }

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        lookback = self.params["lookback"]
        buffer_mult = self.params["min_atr_buffer"]
        min_rvol = self.params["min_rvol"]

        # The range excludes the current bar — otherwise the bar breaking out
        # defines the level it is breaking, and nothing can ever break out.
        prior = df.iloc[-(lookback + 1) : -1]
        resistance = float(prior["high"].max())
        support = float(prior["low"].min())

        close = float(df["close"].iloc[-1])
        atr_now = atr(df, self.params["atr_length"]).iloc[-1]
        rvol_now = relative_volume(df, self.params["vol_length"]).iloc[-1]

        if pd.isna(atr_now) or pd.isna(rvol_now):
            return self.neutral(symbol, "ATR or volume average not yet warmed up")

        atr_now = float(atr_now)
        rvol_now = float(rvol_now)
        buffer = buffer_mult * atr_now

        metrics = {
            "close": close,
            "resistance": resistance,
            "support": support,
            "atr": atr_now,
            "rvol": rvol_now,
            "range_pct": (resistance - support) / support * 100.0 if support else 0.0,
        }

        broke_up = close > resistance + buffer
        broke_down = close < support - buffer

        if not (broke_up or broke_down):
            return self.neutral(symbol, f"inside the {lookback}-bar range", **metrics)

        confirmed = rvol_now >= min_rvol
        # Scale with how far past the level we closed, capped at 1 ATR.
        level = resistance if broke_up else support
        extension = abs(close - level) / atr_now if atr_now else 0.0
        base = 0.5 + 0.3 * min(extension, 1.0)
        strength = base + 0.2 if confirmed else base * 0.5

        direction = SignalDirection.BULLISH if broke_up else SignalDirection.BEARISH
        word = "above resistance" if broke_up else "below support"
        volume_note = (
            f"confirmed by {rvol_now:.1f}x volume"
            if confirmed
            else f"UNCONFIRMED: only {rvol_now:.1f}x volume"
        )

        return self.signal(
            symbol,
            direction,
            strength,
            f"broke {word} {level:.2f} by {extension:.2f} ATR, {volume_note}",
            **metrics,
        )
