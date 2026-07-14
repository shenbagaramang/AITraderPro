"""RSI and MACD momentum, including divergence."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.indicators import macd, rsi
from app.scanners.base import Scanner, Signal, SignalDirection


class MomentumScanner(Scanner):
    """Combines RSI level, MACD cross and RSI divergence.

    Note the deliberate refusal to treat RSI > 70 as bearish. Overbought is not
    a sell signal — in a strong trend RSI sits above 70 for weeks and shorting
    it is how accounts die. It is reported as *strong bullish momentum*, and only
    flagged bearish when it is overbought **and** diverging, which is the case
    where it actually carries information.
    """

    name = "momentum"
    min_bars = 80

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {
            "rsi_length": 14,
            "overbought": 70.0,
            "oversold": 30.0,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "divergence_lookback": 20,
        }

    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        close = df["close"]
        rsi_series = rsi(close, self.params["rsi_length"])
        macd_frame = macd(
            close,
            self.params["macd_fast"],
            self.params["macd_slow"],
            self.params["macd_signal"],
        )

        if pd.isna(rsi_series.iloc[-1]) or pd.isna(macd_frame["signal"].iloc[-1]):
            return self.neutral(symbol, "RSI or MACD not yet warmed up")

        rsi_now = float(rsi_series.iloc[-1])
        hist = macd_frame["histogram"]
        hist_now = float(hist.iloc[-1])
        hist_prev = float(hist.iloc[-2])

        macd_crossed_up = hist_prev <= 0 < hist_now
        macd_crossed_down = hist_prev >= 0 > hist_now

        divergence = self._divergence(close, rsi_series)

        metrics = {
            "rsi": rsi_now,
            "macd": float(macd_frame["macd"].iloc[-1]),
            "macd_signal": float(macd_frame["signal"].iloc[-1]),
            "histogram": hist_now,
        }

        # Divergence at an extreme is the highest-information case.
        if divergence == "bearish" and rsi_now >= self.params["overbought"]:
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                0.8,
                f"bearish divergence: price made a higher high, RSI ({rsi_now:.1f}) "
                "did not, while overbought",
                **metrics,
            )

        if divergence == "bullish" and rsi_now <= self.params["oversold"]:
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                0.8,
                f"bullish divergence: price made a lower low, RSI ({rsi_now:.1f}) "
                "did not, while oversold",
                **metrics,
            )

        if macd_crossed_up:
            strength = 0.75 if rsi_now > 50 else 0.55
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                strength,
                f"MACD crossed above signal, RSI {rsi_now:.1f}",
                **metrics,
            )

        if macd_crossed_down:
            strength = 0.75 if rsi_now < 50 else 0.55
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                strength,
                f"MACD crossed below signal, RSI {rsi_now:.1f}",
                **metrics,
            )

        if rsi_now >= self.params["overbought"]:
            return self.signal(
                symbol,
                SignalDirection.BULLISH,
                0.45,
                f"RSI {rsi_now:.1f}: strong momentum, not a short signal on its own",
                **metrics,
            )

        if rsi_now <= self.params["oversold"]:
            return self.signal(
                symbol,
                SignalDirection.BEARISH,
                0.45,
                f"RSI {rsi_now:.1f}: weak momentum, not a long signal on its own",
                **metrics,
            )

        return self.neutral(symbol, f"RSI {rsi_now:.1f} mid-range, no MACD cross", **metrics)

    def _divergence(self, close: pd.Series, rsi_series: pd.Series) -> str | None:
        """Compare the last two swing extremes in price against those in RSI."""
        n = self.params["divergence_lookback"]
        if len(close) < 2 * n:
            return None

        recent_px, prior_px = close.iloc[-n:], close.iloc[-2 * n : -n]
        recent_rsi, prior_rsi = rsi_series.iloc[-n:], rsi_series.iloc[-2 * n : -n]

        if recent_rsi.isna().any() or prior_rsi.isna().any():
            return None

        if recent_px.max() > prior_px.max() and recent_rsi.max() < prior_rsi.max():
            return "bearish"
        if recent_px.min() < prior_px.min() and recent_rsi.min() > prior_rsi.min():
            return "bullish"
        return None
