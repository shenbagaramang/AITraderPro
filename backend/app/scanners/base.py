"""The contract every scanner implements."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.indicators.base import validate_ohlcv


class SignalDirection(str, enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class Signal:
    """One scanner's verdict on one symbol.

    ``strength`` is 0.0–1.0 and is *within-scanner* only: it says how cleanly
    this scanner's criteria were met, not how good the trade is. Comparing
    strength across scanners is meaningless — weighing them against each other
    is the technical agent's job, not the scanner's.
    """

    scanner: str
    symbol: str
    direction: SignalDirection
    strength: float
    reason: str
    metrics: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be in [0, 1], got {self.strength}")

    @property
    def is_actionable(self) -> bool:
        return self.direction is not SignalDirection.NEUTRAL


@dataclass(frozen=True, slots=True)
class ScanRequest:
    symbol: str
    candles: pd.DataFrame
    params: dict[str, Any] = field(default_factory=dict)


class Scanner(ABC):
    """Base class. Subclasses declare a name, a minimum bar count, and criteria."""

    name: str = "scanner"
    min_bars: int = 50

    def __init__(self, **params: Any) -> None:
        self.params = {**self.defaults(), **params}

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {}

    @abstractmethod
    def evaluate(self, symbol: str, df: pd.DataFrame) -> Signal:
        """Apply this scanner's criteria to indicator output."""

    def scan(self, symbol: str, df: pd.DataFrame) -> Signal:
        """Validate, then evaluate. Insufficient history is neutral, never an error.

        A scanner that raises on a thinly-traded symbol takes the whole scan
        down with it, so a short history is reported as a neutral signal.
        """
        validate_ohlcv(df, 1)
        if len(df) < self.min_bars:
            return self.neutral(
                symbol, f"insufficient history: {len(df)} bars, need {self.min_bars}"
            )
        return self.evaluate(symbol, df)

    def neutral(self, symbol: str, reason: str, **metrics: float) -> Signal:
        return Signal(
            scanner=self.name,
            symbol=symbol,
            direction=SignalDirection.NEUTRAL,
            strength=0.0,
            reason=reason,
            metrics=metrics,
        )

    def signal(
        self,
        symbol: str,
        direction: SignalDirection,
        strength: float,
        reason: str,
        **metrics: float,
    ) -> Signal:
        return Signal(
            scanner=self.name,
            symbol=symbol,
            direction=direction,
            strength=round(min(max(strength, 0.0), 1.0), 4),
            reason=reason,
            metrics={k: round(float(v), 4) for k, v in metrics.items()},
        )
