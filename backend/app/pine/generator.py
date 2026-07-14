"""Template-based Pine v6 generation, one template per scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PINE_VERSION = "//@version=6"

# Shared prologue: non-repaint guard used by every template.
CONFIRM = "barstate.isconfirmed"


@dataclass(frozen=True, slots=True)
class PineScript:
    name: str
    scanner: str
    params: dict[str, Any]
    source: str
    alerts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if PINE_VERSION not in self.source:
            raise ValueError("generated script is missing the version pragma")


class PineGenerator:
    """One method per scanner. Params default to the scanner's own defaults,
    imported from the scanner classes so the two can never drift apart."""

    def generate(self, scanner: str, **overrides: Any) -> PineScript:
        try:
            method = getattr(self, f"_{scanner}")
        except AttributeError as exc:
            known = ", ".join(sorted(self.available()))
            raise KeyError(f"no Pine template for {scanner!r}; available: {known}") from exc
        return method(**overrides)

    @staticmethod
    def available() -> list[str]:
        return ["ema", "bollinger", "momentum", "vwap", "breakout", "supertrend"]

    # --- templates -----------------------------------------------------------
    def _ema(self, **overrides: Any) -> PineScript:
        from app.scanners.ema_scanner import EmaScanner

        p = {**EmaScanner.defaults(), **overrides}
        source = f"""{PINE_VERSION}
indicator("QTS EMA Cross ({p["fast"]}/{p["slow"]}/{p["trend"]})", overlay=true)

fastLen  = input.int({p["fast"]},  "Fast EMA",  minval=1)
slowLen  = input.int({p["slow"]},  "Slow EMA",  minval=1)
trendLen = input.int({p["trend"]}, "Trend EMA", minval=1)

emaFast  = ta.ema(close, fastLen)
emaSlow  = ta.ema(close, slowLen)
emaTrend = ta.ema(close, trendLen)

plot(emaFast,  "Fast",  color=color.new(color.aqua,   0))
plot(emaSlow,  "Slow",  color=color.new(color.orange, 0))
plot(emaTrend, "Trend", color=color.new(color.gray,  30), linewidth=2)

// Signals are evaluated on the CLOSED bar only: no repaint.
crossUp   = ta.crossover(emaFast, emaSlow)  and close > emaTrend and {CONFIRM}
crossDown = ta.crossunder(emaFast, emaSlow) and close < emaTrend and {CONFIRM}

plotshape(crossUp,   "Long",  shape.triangleup,   location.belowbar, color.green, size=size.small)
plotshape(crossDown, "Short", shape.triangledown, location.abovebar, color.red,   size=size.small)

alertcondition(crossUp,   "EMA Cross Long",  "{{{{ticker}}}} EMA{p["fast"]} crossed above EMA{p["slow"]}, price above EMA{p["trend"]}")
alertcondition(crossDown, "EMA Cross Short", "{{{{ticker}}}} EMA{p["fast"]} crossed below EMA{p["slow"]}, price below EMA{p["trend"]}")
"""
        return PineScript(
            name=f"QTS EMA Cross ({p['fast']}/{p['slow']}/{p['trend']})",
            scanner="ema",
            params=p,
            source=source,
            alerts=["EMA Cross Long", "EMA Cross Short"],
        )

    def _bollinger(self, **overrides: Any) -> PineScript:
        from app.scanners.bb_scanner import BollingerScanner

        p = {**BollingerScanner.defaults(), **overrides}
        pct = int(p["squeeze_percentile"] * 100)
        source = f"""{PINE_VERSION}
indicator("QTS Bollinger Squeeze ({p["length"]}, {p["std_dev"]})", overlay=true)

length   = input.int({p["length"]}, "Length", minval=1)
mult     = input.float({p["std_dev"]}, "StdDev", minval=0.1, step=0.1)
lookback = input.int({p["squeeze_lookback"]}, "Squeeze lookback", minval=20)

basis = ta.sma(close, length)
dev   = mult * ta.stdev(close, length)   // ta.stdev is population stdev, matching the scanner
upper = basis + dev
lower = basis - dev

plot(basis, "Basis", color=color.gray)
pUp = plot(upper, "Upper", color=color.new(color.blue, 40))
pLo = plot(lower, "Lower", color=color.new(color.blue, 40))
fill(pUp, pLo, color=color.new(color.blue, 92))

bandwidth = (upper - lower) / basis * 100
threshold = ta.percentile_linear_interpolation(bandwidth, lookback, {pct})
wasSqueezed = bandwidth[1] <= threshold[1]

fireUp   = wasSqueezed and close > upper and {CONFIRM}
fireDown = wasSqueezed and close < lower and {CONFIRM}

bgcolor(bandwidth <= threshold ? color.new(color.yellow, 85) : na, title="Squeeze building")
plotshape(fireUp,   "Squeeze Fire Up",   shape.triangleup,   location.belowbar, color.green, size=size.small)
plotshape(fireDown, "Squeeze Fire Down", shape.triangledown, location.abovebar, color.red,   size=size.small)

alertcondition(fireUp,   "BB Squeeze Fire Long",  "{{{{ticker}}}} squeeze fired upward")
alertcondition(fireDown, "BB Squeeze Fire Short", "{{{{ticker}}}} squeeze fired downward")
"""
        return PineScript(
            name=f"QTS Bollinger Squeeze ({p['length']}, {p['std_dev']})",
            scanner="bollinger",
            params=p,
            source=source,
            alerts=["BB Squeeze Fire Long", "BB Squeeze Fire Short"],
        )

    def _momentum(self, **overrides: Any) -> PineScript:
        from app.scanners.momentum_scanner import MomentumScanner

        p = {**MomentumScanner.defaults(), **overrides}
        source = f"""{PINE_VERSION}
indicator("QTS Momentum (RSI {p["rsi_length"]} / MACD)", overlay=false)

rsiLen   = input.int({p["rsi_length"]}, "RSI length", minval=2)
obLevel  = input.float({p["overbought"]}, "Overbought")
osLevel  = input.float({p["oversold"]},  "Oversold")

rsi = ta.rsi(close, rsiLen)   // ta.rsi is RMA-based, matching the scanner exactly
[macdLine, signalLine, hist] = ta.macd(close, {p["macd_fast"]}, {p["macd_slow"]}, {p["macd_signal"]})

plot(rsi, "RSI", color=color.purple)
hline(obLevel, "OB", color=color.red)
hline(osLevel, "OS", color=color.green)

macdUp   = ta.crossover(hist, 0)  and {CONFIRM}
macdDown = ta.crossunder(hist, 0) and {CONFIRM}

// NOTE, matching the scanner's philosophy: overbought alone is NOT a short.
alertcondition(macdUp,   "MACD Cross Up",   "{{{{ticker}}}} MACD histogram crossed above zero, RSI {{{{plot_0}}}}")
alertcondition(macdDown, "MACD Cross Down", "{{{{ticker}}}} MACD histogram crossed below zero, RSI {{{{plot_0}}}}")
"""
        return PineScript(
            name=f"QTS Momentum (RSI {p['rsi_length']} / MACD)",
            scanner="momentum",
            params=p,
            source=source,
            alerts=["MACD Cross Up", "MACD Cross Down"],
        )

    def _vwap(self, **overrides: Any) -> PineScript:
        from app.scanners.vwap_scanner import VwapScanner

        p = {**VwapScanner.defaults(), **overrides}
        source = f"""{PINE_VERSION}
indicator("QTS VWAP Reclaim", overlay=true)

atrLen  = input.int({p["atr_length"]}, "ATR length", minval=1)
stretch = input.float({p["stretch_atr"]}, "Stretch (ATR multiples)", step=0.5)

vwapLine = ta.vwap(hlc3)   // session-anchored, matching the scanner
atrNow   = ta.atr(atrLen)

plot(vwapLine, "VWAP", color=color.new(color.teal, 0), linewidth=2)

reclaimed = ta.crossover(close, vwapLine)  and {CONFIRM}
lost      = ta.crossunder(close, vwapLine) and {CONFIRM}
distATR   = (close - vwapLine) / atrNow
stretched = math.abs(distATR) >= stretch and {CONFIRM}

plotshape(reclaimed, "Reclaim", shape.triangleup,   location.belowbar, color.green, size=size.tiny)
plotshape(lost,      "Lost",    shape.triangledown, location.abovebar, color.red,   size=size.tiny)

alertcondition(reclaimed, "VWAP Reclaim", "{{{{ticker}}}} reclaimed session VWAP")
alertcondition(lost,      "VWAP Lost",    "{{{{ticker}}}} lost session VWAP")
alertcondition(stretched, "VWAP Stretch", "{{{{ticker}}}} is stretched from VWAP")
"""
        return PineScript(
            name="QTS VWAP Reclaim",
            scanner="vwap",
            params=p,
            source=source,
            alerts=["VWAP Reclaim", "VWAP Lost", "VWAP Stretch"],
        )

    def _breakout(self, **overrides: Any) -> PineScript:
        from app.scanners.breakout_scanner import BreakoutScanner

        p = {**BreakoutScanner.defaults(), **overrides}
        source = f"""{PINE_VERSION}
indicator("QTS Breakout ({p["lookback"]}-bar)", overlay=true)

lookback = input.int({p["lookback"]}, "Range lookback", minval=5)
atrLen   = input.int({p["atr_length"]}, "ATR length", minval=1)
atrBuf   = input.float({p["min_atr_buffer"]}, "ATR buffer", step=0.05)
minRvol  = input.float({p["min_rvol"]}, "Min RVOL", step=0.1)
volLen   = input.int({p["vol_length"]}, "Volume avg length", minval=1)

// The range excludes the current bar — the breaking bar cannot define its own level.
resistance = ta.highest(high[1], lookback)
support    = ta.lowest(low[1],  lookback)
atrNow     = ta.atr(atrLen)
rvol       = volume / ta.sma(volume, volLen)

plot(resistance, "Resistance", color=color.new(color.red,   50), style=plot.style_line)
plot(support,    "Support",    color=color.new(color.green, 50), style=plot.style_line)

brokeUp   = close > resistance + atrBuf * atrNow and {CONFIRM}
brokeDown = close < support    - atrBuf * atrNow and {CONFIRM}
confirmed = rvol >= minRvol

plotshape(brokeUp   and confirmed,     "Confirmed breakout",   shape.triangleup,   location.belowbar, color.green,  size=size.small)
plotshape(brokeUp   and not confirmed, "Unconfirmed breakout", shape.triangleup,   location.belowbar, color.orange, size=size.tiny)
plotshape(brokeDown and confirmed,     "Confirmed breakdown",  shape.triangledown, location.abovebar, color.red,    size=size.small)

alertcondition(brokeUp and confirmed,   "Breakout Confirmed",   "{{{{ticker}}}} broke resistance on volume")
alertcondition(brokeDown and confirmed, "Breakdown Confirmed",  "{{{{ticker}}}} broke support on volume")
alertcondition(brokeUp and not confirmed, "Breakout Unconfirmed", "{{{{ticker}}}} broke resistance on THIN volume")
"""
        return PineScript(
            name=f"QTS Breakout ({p['lookback']}-bar)",
            scanner="breakout",
            params=p,
            source=source,
            alerts=["Breakout Confirmed", "Breakdown Confirmed", "Breakout Unconfirmed"],
        )

    def _supertrend(self, **overrides: Any) -> PineScript:
        p = {"length": 10, "multiplier": 3.0, **overrides}
        source = f"""{PINE_VERSION}
indicator("QTS Supertrend ({p["length"]}, {p["multiplier"]})", overlay=true)

atrLen = input.int({p["length"]}, "ATR length", minval=1)
mult   = input.float({p["multiplier"]}, "Multiplier", step=0.5)

[st, dir] = ta.supertrend(mult, atrLen)

plot(dir < 0 ? st : na, "Up trend",   color=color.green, style=plot.style_linebr)
plot(dir > 0 ? st : na, "Down trend", color=color.red,   style=plot.style_linebr)

flipUp   = ta.change(dir) < 0 and {CONFIRM}
flipDown = ta.change(dir) > 0 and {CONFIRM}

alertcondition(flipUp,   "Supertrend Flip Long",  "{{{{ticker}}}} Supertrend flipped up")
alertcondition(flipDown, "Supertrend Flip Short", "{{{{ticker}}}} Supertrend flipped down")
"""
        return PineScript(
            name=f"QTS Supertrend ({p['length']}, {p['multiplier']})",
            scanner="supertrend",
            params=p,
            source=source,
            alerts=["Supertrend Flip Long", "Supertrend Flip Short"],
        )
