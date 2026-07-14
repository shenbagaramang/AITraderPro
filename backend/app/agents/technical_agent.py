"""Technical agent: turns scanner Signals into a Buy / Sell / Hold call."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.agents.base import Action, Conviction, Recommendation
from app.scanners.base import Signal, SignalDirection
from app.scanners.registry import run_all

# How much each scanner's opinion counts toward the aggregate.
#
# These are judgements, not measurements, and they are stated here in one place
# precisely so they can be argued with and, once there is a backtest, replaced
# with fitted values. Breakout and momentum lead because they identify an event;
# volume is confirmation rather than a thesis of its own; VWAP is intraday-only
# and says little on a daily chart.
DEFAULT_WEIGHTS: dict[str, float] = {
    "breakout": 1.3,
    "momentum": 1.2,
    "adx": 1.2,
    "bollinger": 1.1,
    "ichimoku": 1.0,
    "ema": 1.0,
    "volume": 0.9,
    "vwap": 0.7,
}

# Scanners whose edge depends on a trend actually existing. In a ranging market
# (low ADX) these are the ones that generate the most confident nonsense, so
# they are the ones discounted.
TREND_FOLLOWING = frozenset({"ema", "breakout", "ichimoku", "adx"})

RANGING_ADX = 20.0
RANGE_PENALTY = 0.5

CONVICTION_BANDS = ((0.65, Conviction.HIGH), (0.35, Conviction.MODERATE))


@dataclass(frozen=True, slots=True)
class TechnicalView:
    """The agent's full read on one symbol, including the dissent."""

    symbol: str
    bias: SignalDirection
    score: float  # -1.0 (max bearish) .. +1.0 (max bullish)
    conviction: Conviction
    agreement: float  # share of actionable signals on the winning side
    regime: str  # trending | ranging | unknown
    signals: list[Signal] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def is_actionable(self) -> bool:
        """A direction alone is not a trade. Low conviction, or a directional read
        in a ranging market, both mean 'do nothing'."""
        if self.bias is SignalDirection.NEUTRAL or self.conviction is Conviction.LOW:
            return False
        return not (self.regime == "ranging" and self.conviction is not Conviction.HIGH)

    def to_recommendation(self) -> Recommendation:
        action = {
            SignalDirection.BULLISH: Action.BUY,
            SignalDirection.BEARISH: Action.SELL,
            SignalDirection.NEUTRAL: Action.HOLD,
        }[self.bias]

        # A directional bias in a ranging market is not a trade. Say HOLD.
        if self.regime == "ranging" and self.conviction is not Conviction.HIGH:
            action = Action.HOLD

        return Recommendation(
            agent="technical",
            symbol=self.symbol,
            action=action,
            confidence=round(abs(self.score), 4),
            conviction=self.conviction,
            explanation=self.rationale,
            concerns=self.conflicts,
            metrics={"score": self.score, "agreement": self.agreement},
        )

    def summary(self) -> str:
        if self.bias is SignalDirection.NEUTRAL:
            return f"{self.symbol}: no directional edge ({len(self.signals)} scanners run)"
        dissent = f", {len(self.conflicts)} disagree" if self.conflicts else ""
        return (
            f"{self.symbol}: {self.bias.value}, {self.conviction.value} conviction "
            f"[{self.regime}] (score {self.score:+.2f}, "
            f"{self.agreement:.0%} agreement{dissent})"
        )


class TechnicalAgent:
    """Aggregates scanner signals into a weighted directional view.

    Three things this deliberately does *not* do:

    - It does not recompute any indicator. Every number it reports came from a
      Signal's ``metrics`` — including the ADX reading it uses to detect the
      regime, which is why ADX is a scanner and not an inline calculation.
    - It does not hide disagreement. A 6-0 sweep and a 4-2 split can produce a
      similar score and are not the same situation, so ``agreement`` is reported
      separately, dissenters are named, and agreement *gates* conviction.
    - It does not size the position or pick a stop. That is the risk agent's job.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    def analyze(
        self, symbol: str, df: pd.DataFrame, *, only: list[str] | None = None
    ) -> TechnicalView:
        return self.interpret(symbol, run_all(symbol, df, only=only))

    def recommend(self, symbol: str, df: pd.DataFrame) -> Recommendation:
        return self.analyze(symbol, df).to_recommendation()

    def interpret(self, symbol: str, signals: list[Signal]) -> TechnicalView:
        regime, adx_value = self._regime(signals)
        actionable = [s for s in signals if s.is_actionable]

        if not actionable:
            return self._flat(symbol, signals, regime, ["every scanner returned neutral"])

        bullish = [s for s in actionable if s.direction is SignalDirection.BULLISH]
        bearish = [s for s in actionable if s.direction is SignalDirection.BEARISH]

        bull = sum(self._effective_weight(s, regime) * s.strength for s in bullish)
        bear = sum(self._effective_weight(s, regime) * s.strength for s in bearish)

        # Normalise by the weight that could have voted, so a 2-scanner scan and
        # an 8-scanner scan land on the same scale.
        total = sum(self._effective_weight(s, regime) for s in actionable) or 1.0
        score = (bull - bear) / total

        if score == 0.0:
            return self._flat(
                symbol,
                signals,
                regime,
                ["bullish and bearish signals cancel out exactly"],
                conflicts=[f"{s.scanner}: {s.reason}" for s in actionable],
            )

        if score > 0.0:
            bias, winners, dissenters = SignalDirection.BULLISH, bullish, bearish
        else:
            bias, winners, dissenters = SignalDirection.BEARISH, bearish, bullish

        agreement = len(winners) / len(actionable)
        rationale = [f"{s.scanner}: {s.reason}" for s in winners]
        conflicts = [f"{s.scanner}: {s.reason}" for s in dissenters]

        if regime == "ranging":
            conflicts.insert(
                0,
                f"regime: ADX {adx_value:.1f} — market is ranging, "
                "trend-following signals discounted",
            )

        return TechnicalView(
            symbol=symbol,
            bias=bias,
            score=round(score, 4),
            conviction=self._conviction(abs(score), agreement),
            agreement=round(agreement, 4),
            regime=regime,
            signals=signals,
            rationale=rationale,
            conflicts=conflicts,
        )

    # --- internals ---------------------------------------------------------
    def _regime(self, signals: list[Signal]) -> tuple[str, float]:
        """Read the regime out of the ADX scanner's metrics. Compute nothing."""
        for signal in signals:
            if signal.scanner == "adx" and "adx" in signal.metrics:
                value = signal.metrics["adx"]
                return ("ranging" if value < RANGING_ADX else "trending", value)
        return ("unknown", float("nan"))

    def _effective_weight(self, signal: Signal, regime: str) -> float:
        weight = self.weights.get(signal.scanner, 1.0)
        if regime == "ranging" and signal.scanner in TREND_FOLLOWING:
            return weight * RANGE_PENALTY
        return weight

    def _conviction(self, magnitude: float, agreement: float) -> Conviction:
        # Agreement gates conviction: a strong score built on a split vote is not
        # a high-conviction setup, however large the number looks.
        adjusted = magnitude * (0.5 + 0.5 * agreement)
        for threshold, label in CONVICTION_BANDS:
            if adjusted >= threshold:
                return label
        return Conviction.LOW

    def _flat(
        self,
        symbol: str,
        signals: list[Signal],
        regime: str,
        rationale: list[str],
        conflicts: list[str] | None = None,
    ) -> TechnicalView:
        return TechnicalView(
            symbol=symbol,
            bias=SignalDirection.NEUTRAL,
            score=0.0,
            conviction=Conviction.LOW,
            agreement=0.0,
            regime=regime,
            signals=signals,
            rationale=rationale,
            conflicts=conflicts or [],
        )
