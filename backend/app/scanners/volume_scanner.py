"""Unusual volume, and whether it is being paid for."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.indicators import obv, relative_volume, sma
from app.scanners.base import Scanner, Signal, SignalDirection


class VolumeScanner(Scanner):
    """Detects a volume spike and reads its direction from the bar's own close.

    Volume on its own has no direction — 5x volume on a bar that closes on its
    low is distribution, the same 5x closing on its high is accumulation. So the
    spike is graded by where the bar closed within its own range, with OBV slope
    as a secondary confirmation.
    """

    name = "volume"
    min_bars = 40

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {"length": 20, "spike_rvol": 2.0, "obv_slope_length": 10}

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        spike_threshold = self.params["spike_rvol"]

        rvol_now = relative_volume(df, self.params["length"]).iloc[-1]
        if pd.isna(rvol_now):
            return self.neutral(symbol, "volume average not yet warmed up")
        rvol_now = float(rvol_now)

        bar = df.iloc[-1]
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
        bar_range = high - low

        # Close location value: 1.0 = closed on the high, 0.0 = on the low.
        clv = (close - low) / bar_range if bar_range > 0 else 0.5

        obv_series = obv(df)
        obv_ma = sma(obv_series, self.params["obv_slope_length"])
        obv_rising = (
            bool(obv_series.iloc[-1] > obv_ma.iloc[-1])
            if not pd.isna(obv_ma.iloc[-1])
            else False
        )

        metrics = {
            "rvol": rvol_now,
            "close_location": clv,
            "volume": float(bar["volume"]),
            "obv": float(obv_series.iloc[-1]),
        }

        if rvol_now < spike_threshold:
            return self.neutral(symbol, f"volume normal at {rvol_now:.1f}x average", **metrics)

        # Strength grows with the spike, saturating at 4x.
        magnitude = min((rvol_now - spike_threshold) / (4.0 - spike_threshold), 1.0)

        if clv >= 0.66:
            strength = 0.5 + 0.3 * magnitude + (0.15 if obv_rising else 0.0)
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                strength,
                f"{rvol_now:.1f}x volume, closed in the top third of the bar"
                + (", OBV rising" if obv_rising else ""),
                **metrics,
            )

        if clv <= 0.33:
            strength = 0.5 + 0.3 * magnitude + (0.15 if not obv_rising else 0.0)
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                strength,
                f"{rvol_now:.1f}x volume, closed in the bottom third of the bar"
                + (", OBV falling" if not obv_rising else ""),
                **metrics,
            )

        return self.neutral(
            symbol,
            f"{rvol_now:.1f}x volume but closed mid-range: churn, no clear side",
            **metrics,
        )
