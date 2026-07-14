"""News agent and market-context agent.

**These two were one agent in the original spec, and separating them is a
deliberate change.** Per-symbol news (an earnings beat, a block deal, a
resignation) and market-wide context (an RBI policy decision, crude at $95,
USD/INR at 90) have different cadences, different consumers and different blast
radius. A crude spike does not make you re-evaluate one stock; it makes you
re-evaluate every airline and paint company you hold, and it should not have to
be re-fetched once per symbol to do so.

As with fundamentals: the aggregation logic here is real and tested. The feed is
a port with no adapter. Nothing in this module invents a headline.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.agents.base import Action, Conviction, Recommendation

if TYPE_CHECKING:
    from app.agents.providers import MarketContextProvider, NewsProvider


class Sentiment(str, enum.Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class NewsCategory(str, enum.Enum):
    EARNINGS = "earnings"
    ANNOUNCEMENT = "announcement"
    CORPORATE_ACTION = "corporate_action"
    MANAGEMENT = "management"
    SECTOR = "sector"
    REGULATORY = "regulatory"
    OTHER = "other"


# Not all news is equal. An earnings release moves a stock; a sector think-piece
# does not. These multipliers are how that gets expressed.
CATEGORY_WEIGHT = {
    NewsCategory.EARNINGS: 1.5,
    NewsCategory.REGULATORY: 1.3,
    NewsCategory.CORPORATE_ACTION: 1.2,
    NewsCategory.MANAGEMENT: 1.1,
    NewsCategory.ANNOUNCEMENT: 1.0,
    NewsCategory.SECTOR: 0.7,
    NewsCategory.OTHER: 0.5,
}

HALF_LIFE_DAYS = 3.0


@dataclass(frozen=True, slots=True)
class NewsItem:
    symbol: str
    headline: str
    published_at: datetime
    sentiment: Sentiment
    category: NewsCategory = NewsCategory.OTHER
    confidence: float = 1.0  # how sure the classifier is about the sentiment
    source: str = "unknown"
    url: str | None = None


@dataclass(frozen=True, slots=True)
class MarketContext:
    """The macro backdrop. One fetch serves the whole scan."""

    as_of: datetime
    nifty_change_pct: float | None = None
    india_vix: float | None = None
    usd_inr: float | None = None
    usd_inr_change_pct: float | None = None
    crude_usd: float | None = None
    crude_change_pct: float | None = None
    repo_rate: float | None = None
    rbi_event_today: bool = False
    global_cues: Sentiment = Sentiment.NEUTRAL
    notes: list[str] = field(default_factory=list)

    @property
    def risk_off(self) -> bool:
        """A crude, explicit definition, so it can be argued with."""
        signals = [
            self.india_vix is not None and self.india_vix > 20,
            self.nifty_change_pct is not None and self.nifty_change_pct < -1.0,
            self.crude_change_pct is not None and self.crude_change_pct > 5.0,
            self.global_cues is Sentiment.NEGATIVE,
        ]
        return sum(bool(s) for s in signals) >= 2


@dataclass(frozen=True, slots=True)
class NewsAssessment:
    symbol: str
    score: float  # -1.0 .. +1.0
    item_count: int
    dominant: Sentiment
    headlines: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)

    def to_recommendation(self) -> Recommendation:
        if self.item_count == 0:
            return Recommendation(
                agent="news",
                symbol=self.symbol,
                action=Action.HOLD,
                confidence=0.0,
                conviction=Conviction.LOW,
                explanation=["no news in the window"],
            )

        if self.score > 0.25:
            action = Action.BUY
        elif self.score < -0.25:
            action = Action.SELL
        else:
            action = Action.HOLD

        # One article is an anecdote. Conviction needs corroboration.
        if self.item_count >= 3 and abs(self.score) >= 0.5:
            conviction = Conviction.HIGH
        elif abs(self.score) >= 0.25:
            conviction = Conviction.MODERATE
        else:
            conviction = Conviction.LOW

        return Recommendation(
            agent="news",
            symbol=self.symbol,
            action=action,
            confidence=round(min(abs(self.score), 1.0), 4),
            conviction=conviction,
            explanation=self.headlines,
            concerns=self.concerns,
            metrics={"score": self.score, "item_count": float(self.item_count)},
        )


class NewsAgent:
    """Aggregates per-symbol news into a decayed, category-weighted sentiment score.

    Time decay matters more than it looks. Without it, a three-week-old downgrade
    counts as loudly as this morning's earnings beat, and the agent ends up
    trading last month's story.
    """

    def __init__(
        self,
        provider: NewsProvider | None = None,
        half_life_days: float = HALF_LIFE_DAYS,
    ) -> None:
        if provider is None:
            from app.agents.providers import UnconfiguredNews

            provider = UnconfiguredNews()
        self.provider = provider
        self.half_life_days = half_life_days

    def analyze(self, symbol: str, lookback_days: int = 7) -> NewsAssessment:
        """Fetch and assess. Raises ProviderNotConfiguredError until an adapter exists."""
        since = (datetime.now(UTC) - timedelta(days=lookback_days)).date()
        return self.assess(symbol, self.provider.recent(symbol, since))

    def assess(
        self, symbol: str, items: list[NewsItem], now: datetime | None = None
    ) -> NewsAssessment:
        now = now or datetime.now(UTC)

        if not items:
            return NewsAssessment(
                symbol=symbol, score=0.0, item_count=0, dominant=Sentiment.NEUTRAL
            )

        polarity = {Sentiment.POSITIVE: 1.0, Sentiment.NEGATIVE: -1.0, Sentiment.NEUTRAL: 0.0}

        weighted = 0.0
        total_weight = 0.0
        counts = dict.fromkeys(Sentiment, 0)

        for item in items:
            age_days = max((now - item.published_at).total_seconds() / 86400.0, 0.0)
            decay = 0.5 ** (age_days / self.half_life_days)
            weight = CATEGORY_WEIGHT[item.category] * item.confidence * decay

            weighted += polarity[item.sentiment] * weight
            total_weight += weight
            counts[item.sentiment] += 1

        score = weighted / total_weight if total_weight else 0.0
        dominant = max(counts, key=lambda s: counts[s])

        # Surface the loudest items: recent, high-impact, non-neutral.
        ranked = sorted(
            (i for i in items if i.sentiment is not Sentiment.NEUTRAL),
            key=lambda i: CATEGORY_WEIGHT[i.category] * i.confidence,
            reverse=True,
        )
        headlines = [f"[{i.category.value}] {i.headline}" for i in ranked[:5]]

        concerns = []
        if counts[Sentiment.POSITIVE] and counts[Sentiment.NEGATIVE]:
            concerns.append(
                f"mixed coverage: {counts[Sentiment.POSITIVE]} positive, "
                f"{counts[Sentiment.NEGATIVE]} negative"
            )

        return NewsAssessment(
            symbol=symbol,
            score=round(score, 4),
            item_count=len(items),
            dominant=dominant,
            headlines=headlines,
            concerns=concerns,
        )


class MarketContextAgent:
    """The macro read. Fetched once per scan, not once per symbol."""

    def __init__(self, provider: MarketContextProvider | None = None) -> None:
        self.provider = provider

    def assess(self, context: MarketContext) -> list[str]:
        """Turn the backdrop into plain-language cautions."""
        notes: list[str] = []

        if context.rbi_event_today:
            notes.append("RBI policy today — expect a volatility spike around the decision")
        if context.india_vix is not None and context.india_vix > 20:
            notes.append(f"India VIX at {context.india_vix:.1f} — elevated; size down")
        if context.crude_change_pct is not None and context.crude_change_pct > 5:
            notes.append(
                f"crude +{context.crude_change_pct:.1f}% — headwind for oil marketing, "
                "paints, airlines, tyres"
            )
        if context.usd_inr_change_pct is not None and context.usd_inr_change_pct > 0.5:
            notes.append(
                f"rupee weak ({context.usd_inr_change_pct:+.2f}%) — tailwind for IT and "
                "pharma exporters, headwind for importers"
            )
        if context.global_cues is Sentiment.NEGATIVE:
            notes.append("negative global cues")
        if context.risk_off:
            notes.append(
                "RISK-OFF backdrop: two or more stress signals are firing. "
                "Long signals should clear a higher bar today."
            )

        return notes
