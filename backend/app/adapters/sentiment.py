"""Headline classification: sentiment + category.

Two classifiers behind one interface:

- ``LexiconSentimentClassifier`` — keyword scoring. Deterministic, free,
  transparent, and knowably crude: it cannot read negation ("failed to miss
  estimates") or sarcasm. Its confidence is capped at 0.7 for exactly that
  reason, so lexicon-scored items can never dominate a NewsAgent aggregate the
  way a genuinely understood headline could.
- ``ClaudeSentimentClassifier`` — the Anthropic API. Reads nuance, costs money,
  needs a key. Falls back to the lexicon per-batch on any API failure, because
  a news agent that goes silent during an outage is worse than one that gets
  slightly dumber.

Category classification is keyword-rule based in both; the categories are
coarse enough that rules do fine.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.agents.news_agent import NewsCategory, Sentiment
from app.core.logging import get_logger

logger = get_logger(__name__)

POSITIVE = {
    "beat",
    "beats",
    "surge",
    "surges",
    "record",
    "profit",
    "profits",
    "jumps",
    "gains",
    "upgrade",
    "upgraded",
    "outperform",
    "buyback",
    "bonus",
    "wins",
    "won",
    "bags",
    "strong",
    "robust",
    "expansion",
    "growth",
    "dividend",
    "highest",
    "soars",
    "rally",
    "approves",
    "approval",
}
NEGATIVE = {
    "miss",
    "misses",
    "falls",
    "fall",
    "plunge",
    "plunges",
    "loss",
    "losses",
    "downgrade",
    "downgraded",
    "underperform",
    "fraud",
    "probe",
    "penalty",
    "fine",
    "fined",
    "resigns",
    "resignation",
    "default",
    "weak",
    "slump",
    "cuts",
    "cut",
    "slashed",
    "layoffs",
    "strike",
    "recall",
    "lawsuit",
    "crash",
    "warns",
    "warning",
    "pledge",
}

CATEGORY_RULES: list[tuple[NewsCategory, tuple[str, ...]]] = [
    (
        NewsCategory.EARNINGS,
        (
            "results",
            "earnings",
            "q1",
            "q2",
            "q3",
            "q4",
            "quarterly",
            "profit",
            "revenue",
            "ebitda",
            "guidance",
        ),
    ),
    (
        NewsCategory.CORPORATE_ACTION,
        (
            "dividend",
            "split",
            "buyback",
            "bonus issue",
            "rights issue",
            "merger",
            "acquisition",
            "demerger",
            "delisting",
            "ipo",
        ),
    ),
    (
        NewsCategory.MANAGEMENT,
        (
            "ceo",
            "cfo",
            "director",
            "resigns",
            "appoints",
            "appointed",
            "steps down",
            "chairman",
        ),
    ),
    (
        NewsCategory.REGULATORY,
        (
            "sebi",
            "rbi",
            "nclt",
            "supreme court",
            "high court",
            "penalty",
            "probe",
            "investigation",
            "cci",
            "gst",
        ),
    ),
    (
        NewsCategory.ANNOUNCEMENT,
        (
            "announces",
            "launches",
            "wins order",
            "bags",
            "contract",
            "partnership",
            "expansion",
            "plant",
        ),
    ),
]

_WORD = re.compile(r"[a-z][a-z\-']*")


@dataclass(frozen=True, slots=True)
class Classified:
    sentiment: Sentiment
    category: NewsCategory
    confidence: float


def classify_category(headline: str) -> NewsCategory:
    lowered = headline.lower()
    for category, keywords in CATEGORY_RULES:
        if any(k in lowered for k in keywords):
            return category
    return NewsCategory.OTHER


class LexiconSentimentClassifier:
    MAX_CONFIDENCE = 0.7  # a keyword count is not comprehension

    def classify(self, headline: str) -> Classified:
        words = set(_WORD.findall(headline.lower()))

        pos = sum(1 for w in POSITIVE if w in words)
        neg = sum(1 for w in NEGATIVE if w in words)

        if pos > neg:
            sentiment = Sentiment.POSITIVE
        elif neg > pos:
            sentiment = Sentiment.NEGATIVE
        else:
            sentiment = Sentiment.NEUTRAL

        margin = abs(pos - neg)
        confidence = min(0.4 + 0.15 * margin, self.MAX_CONFIDENCE) if margin else 0.3

        return Classified(
            sentiment=sentiment,
            category=classify_category(headline),
            confidence=round(confidence, 2),
        )

    def classify_many(self, headlines: Iterable[str]) -> list[Classified]:
        return [self.classify(h) for h in headlines]


class ClaudeSentimentClassifier:
    """Batch classification via the Anthropic API. Falls back to the lexicon."""

    MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, api_key: str | None = None) -> None:
        import os

        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._fallback = LexiconSentimentClassifier()

    def classify_many(self, headlines: list[str]) -> list[Classified]:
        if not headlines:
            return []
        if not self.api_key:
            logger.warning("no ANTHROPIC_API_KEY; using the lexicon classifier")
            return self._fallback.classify_many(headlines)

        try:
            return self._via_api(headlines)
        except Exception as exc:  # noqa: BLE001 - degrade, don't go silent
            logger.warning("Claude classification failed (%s); lexicon fallback", exc)
            return self._fallback.classify_many(headlines)

    def classify(self, headline: str) -> Classified:
        return self.classify_many([headline])[0]

    def _via_api(self, headlines: list[str]) -> list[Classified]:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        numbered = "\n".join(f"{i}. {h}" for i, h in enumerate(headlines))
        categories = ", ".join(c.value for c in NewsCategory)

        message = client.messages.create(
            model=self.MODEL,
            max_tokens=1024,
            system=(
                "You classify Indian equity-market headlines. Respond ONLY with a "
                "JSON array, one object per headline, in order: "
                '{"sentiment": "positive|negative|neutral", '
                f'"category": one of [{categories}], '
                '"confidence": 0.0-1.0}. Sentiment is from a shareholder'
                "'s perspective. No prose, no markdown fences."
            ),
            messages=[{"role": "user", "content": numbered}],
        )

        text = message.content[0].text.strip()
        rows = json.loads(text)
        if len(rows) != len(headlines):
            raise ValueError(f"expected {len(headlines)} classifications, got {len(rows)}")

        return [
            Classified(
                sentiment=Sentiment(r["sentiment"]),
                category=NewsCategory(r["category"]),
                confidence=float(r["confidence"]),
            )
            for r in rows
        ]
