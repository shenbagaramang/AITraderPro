"""The engine's inputs and its verdict."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from app.agents.base import Action
from app.agents.fundamental_agent import FundamentalScore
from app.agents.news_agent import MarketContext, NewsAssessment
from app.agents.risk_agent import RiskAssessment
from app.agents.technical_agent import TechnicalView


class DecisionOutcome(str, enum.Enum):
    TRADE = "trade"
    NO_TRADE = "no_trade"
    VETOED = "vetoed"


@dataclass(frozen=True, slots=True)
class MarketData:
    """Everything the engine is allowed to look at for one symbol.

    Only ``candles`` is required. The engine degrades honestly when the optional
    agents have no data rather than pretending their silence is agreement.
    """

    symbol: str
    candles: pd.DataFrame
    fundamentals: FundamentalScore | None = None
    news: NewsAssessment | None = None
    context: MarketContext | None = None
    returns: pd.DataFrame | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    """Why the engine did, or did not, act.

    This object is persisted verbatim onto the order as its ``rationale``. Six
    months later, reviewing a loss, the question is never "what did I buy" but
    "what was I thinking" — and this is the answer.
    """

    symbol: str
    outcome: DecisionOutcome
    action: Action
    confidence: float

    quantity: int = 0
    entry: float | None = None
    stop_loss: float | None = None
    target: float | None = None

    technical: TechnicalView | None = None
    risk: RiskAssessment | None = None

    reasons: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    agent_votes: dict[str, str] = field(default_factory=dict)
    decided_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def should_trade(self) -> bool:
        return self.outcome is DecisionOutcome.TRADE and self.quantity > 0

    def to_dict(self) -> dict:
        """Serialised onto the order record."""
        return {
            "symbol": self.symbol,
            "outcome": self.outcome.value,
            "action": self.action.value,
            "confidence": self.confidence,
            "quantity": self.quantity,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "target": self.target,
            "agent_votes": self.agent_votes,
            "reasons": self.reasons,
            "vetoes": self.vetoes,
            "decided_at": self.decided_at.isoformat(),
        }

    def summary(self) -> str:
        if self.outcome is DecisionOutcome.VETOED:
            return f"{self.symbol}: VETOED — {self.vetoes[0] if self.vetoes else 'risk'}"
        if self.outcome is DecisionOutcome.NO_TRADE:
            reason = self.reasons[0] if self.reasons else "no edge"
            return f"{self.symbol}: no trade — {reason}"
        return (
            f"{self.symbol}: {self.action.value.upper()} {self.quantity} "
            f"@ {self.entry:.2f}, stop {self.stop_loss:.2f} "
            f"(confidence {self.confidence:.2f})"
        )
