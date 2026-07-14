# indicators → scanners → agents

The rule, and the only rule: **each layer may import only from the layer below it.**

```
indicators/   pure math            ema(close, 9)  ->  Series
     ^
scanners/     criteria on math     "EMA9 crossed EMA21, 2.3x volume"  ->  Signal
     ^
agents/       interpretation       "bullish, moderate, but volume disagrees"  ->  TechnicalView
     ^
engine/       decision             entry, stop, size  ->  Order        (next)
```

## Why this, rather than the flat tree

In the flat layout, `ema_scanner.py` and `technical_agent.py` each need an EMA. Left alone, each grows its own. Then one uses `ewm(adjust=False)` seeded from the first bar and the other seeds from an SMA, and they disagree by a few tenths for the first fifty bars — which is exactly long enough for a backtest to look fine and a live signal to fire on a bar the chart says nothing happened on. That class of bug does not announce itself; it just quietly costs money.

Here there is one `ema()`. If it is wrong, everything is wrong in the same direction, and one test fixes it everywhere.

## What each layer may and may not do

**`indicators/`** — pure functions. Series or OHLCV frame in, Series or frame out. No DB, no broker, no config, no logging, no clock. Testable against hand-computed values.

Smoothing matches Pine Script exactly, because a signal that does not reconcile with the chart is worse than no signal:

| Function | Convention | Trap it avoids |
| --- | --- | --- |
| `ema` | seeded with SMA of the first `length` bars | raw `ewm` drifts from TradingView for ~50 bars |
| `rma` | Wilder, alpha = 1/length | using 2/(n+1) here is *the* reason Python RSI disagrees with the chart |
| `rsi` | built on `rma` | as above |
| `bollinger_bands` | population stdev, ddof=0 | pandas defaults to ddof=1 and quietly widens the bands |
| `vwap` | resets each session | a VWAP that never resets is not the VWAP anyone means |

**`scanners/`** — apply criteria, compute nothing. Every number a scanner reasons about came out of `indicators/`. OHLCV in, `Signal` out. Also pure: no DB, no broker.

A `Signal` carries `direction`, `strength` (0–1), a human `reason`, and the `metrics` it decided on. `strength` is **within-scanner only** — it says how cleanly *these* criteria were met. Comparing strength across scanners is meaningless; weighing them is the agent's job.

Insufficient history returns a neutral Signal, never an exception, so one thin symbol cannot take a 200-symbol scan down with it. `run_all()` extends the same courtesy to a scanner that throws.

**`agents/`** — interpret. The technical agent consumes `Signal`s and produces a `TechnicalView`: bias, weighted score, conviction, agreement, and the named dissenters.

Three things it deliberately refuses to do:

1. **Recompute anything.** Every number it reports came from a Signal.
2. **Hide disagreement.** A 6–0 sweep and a 4–2 split can produce a similar score and are not the same situation. `agreement` is reported separately, dissenters are named, and agreement *gates* conviction — a strong score on a split vote cannot reach "high".
3. **Size the position.** That is the Decision Engine's job. Keeping it out means the agent is testable without a portfolio or a broker.

## Two opinions baked into the scanners

Both are contestable. They are written down here so they can be argued with rather than discovered by reading source.

**Overbought is not a sell signal.** RSI > 70 is reported as *strong bullish momentum*, not bearish. In a real trend RSI sits above 70 for weeks, and shorting it is how accounts die. It only turns bearish when overbought **and diverging** — the case where it actually carries information.

**Volume has no direction of its own.** A 5x volume bar closing on its low is distribution; the same 5x closing on its high is accumulation. The volume scanner grades the spike by where the bar closed within its own range, and calls a mid-range close "churn, no clear side" rather than guessing.

## The weights are guesses

`DEFAULT_WEIGHTS` in `technical_agent.py` — breakout 1.3, momentum 1.2, bollinger 1.1, ema 1.0, volume 0.9, vwap 0.7 — are judgements, not measurements. They live in one named constant precisely so they can be replaced with fitted values once the backtester exists. Treat them as a placeholder with a plausible shape, not as a result.

## A worked example

Consolidation, then a 20-bar ramp on rising volume:

```
RELIANCE: bullish, low conviction (score +0.23, 67% agreement, 1 scanner disagrees)

AGREES:
  + ema: EMA stack aligned bullish (9 > 21, price > 50)
  + momentum: RSI 91.0: strong momentum, not a short signal on its own
DISAGREES:
  - vwap: stretched 9.41 ATR above VWAP: extended, mean-reversion risk

actionable: False
```

Two details worth reading carefully, because they are the system working rather than failing:

- **The breakout scanner returned neutral**, on what looks like a breakout. It is right. Its range window excludes the current bar but *includes* the last 20 — and the ramp has been running for 20 bars, so the move is already inside the range it would have to break. After twenty bars, this is a trend, not a breakout. A scanner that fired here would be firing on every bar of every trend.
- **The verdict is "not actionable"** despite two bullish scanners. Price is 9 ATR above VWAP with RSI at 91. The honest read is *extended*, and the agent says so instead of laundering two agreeing scanners into a buy.
