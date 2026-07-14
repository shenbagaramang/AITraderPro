"""Shared vocabulary for the agent layer."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Action(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Conviction(str, enum.Enum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


@dataclass(frozen=True, slots=True)
class Recommendation:
    """What an agent concluded, and why.

    ``confidence`` is 0.0–1.0 and answers "how sure is this agent about *its own*
    call", not "how much money should this trade get". Sizing is the risk agent's
    job and is deliberately not expressible here.
    """

    agent: str
    symbol: str
    action: Action
    confidence: float
    conviction: Conviction
    explanation: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    @property
    def is_actionable(self) -> bool:
        return self.action is not Action.HOLD and self.conviction is not Conviction.LOW
