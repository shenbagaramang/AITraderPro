"""Bollinger squeeze and band excursions."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.indicators import bollinger_bands
from app.scanners.base import Scanner, Signal, SignalDirection


class BollingerScanner(Scanner):
    """Two distinct setups, in priority order.

    1. **Squeeze fire** — bandwidth was in its own lowest percentile, and price
       has just closed outside the band. Compression resolving into expansion.
    2. **Band excursion** — price closed outside a band without a preceding
       squeeze. Reported at a much lower strength, because in a trend this is
       continuation and in a range it is mean-reversion, and a scanner alone
       cannot tell which. That ambiguity is passed up to the agent rather than
       being guessed at here.

    A squeeze that has *not* fired is reported as neutral with the bandwidth in
    metrics — it is a watchlist condition, not a trade.
    """

    name = "bollinger"
    min_bars = 140

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {
            "length": 20,
            "std_dev": 2.0,
            "squeeze_lookback": 120,
            "squeeze_percentile": 0.20,
        }

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        close = df["close"]
        bands = bollinger_bands(close, self.params["length"], self.params["std_dev"])

        if pd.isna(bands["upper"].iloc[-1]):
            return self.neutral(symbol, "bands not yet warmed up")

        price = float(close.iloc[-1])
        upper = float(bands["upper"].iloc[-1])
        lower = float(bands["lower"].iloc[-1])
        bandwidth = bands["bandwidth"]
        bw_now = float(bandwidth.iloc[-1])

        history = bandwidth.iloc[-self.params["squeeze_lookback"] :].dropna()
        threshold = float(history.quantile(self.params["squeeze_percentile"]))

        # Was it compressed on the *previous* bar? The expansion bar itself
        # widens the bands, so testing the current bar would hide every squeeze.
        bw_prev = float(bandwidth.iloc[-2])
        was_squeezed = bw_prev <= threshold

        metrics = {
            "close": price,
            "upper": upper,
            "lower": lower,
            "bandwidth": bw_now,
            "bandwidth_prev": bw_prev,
            "squeeze_threshold": threshold,
            "percent_b": float(bands["percent_b"].iloc[-1]),
        }

        above, below = price > upper, price < lower

        if was_squeezed and (above or below):
            direction = SignalDirection.BULLISH if above else SignalDirection.BEARISH
            side = "upper" if above else "lower"
            return self.signal(
                symbol,
                direction,
                0.9,
                f"squeeze fired: bandwidth {bw_prev:.2f}% was under the "
                f"{int(self.params['squeeze_percentile'] * 100)}th percentile "
                f"({threshold:.2f}%), price broke the {side} band",
                **metrics,
            )

        if was_squeezed:
            return self.neutral(
                symbol,
                f"squeeze building: bandwidth {bw_now:.2f}% at multi-bar lows, "
                "direction not yet declared",
                **metrics,
            )

        if above or below:
            direction = SignalDirection.BULLISH if above else SignalDirection.BEARISH
            side = "upper" if above else "lower"
            return self.signal(
                symbol,
                direction,
                0.35,
                f"closed outside the {side} band with no prior squeeze: "
                "continuation or exhaustion, ambiguous alone",
                **metrics,
            )

        return self.neutral(symbol, "price inside the bands", **metrics)
