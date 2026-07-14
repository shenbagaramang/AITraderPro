"""News and market-context agents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents import (
    Action,
    Conviction,
    MarketContext,
    MarketContextAgent,
    NewsAgent,
    NewsCategory,
    NewsItem,
    Sentiment,
)
from app.agents.providers import ProviderNotConfiguredError

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def item(
    sentiment: Sentiment,
    days_ago: float = 0.0,
    category: NewsCategory = NewsCategory.ANNOUNCEMENT,
    headline: str = "headline",
) -> NewsItem:
    return NewsItem(
        symbol="X",
        headline=headline,
        published_at=NOW - timedelta(days=days_ago),
        sentiment=sentiment,
        category=category,
    )


class TestSentimentAggregation:
    def test_uniformly_positive_news_scores_positive(self) -> None:
        assessment = NewsAgent().assess("X", [item(Sentiment.POSITIVE)] * 3, now=NOW)
        assert assessment.score == pytest.approx(1.0)
        assert assessment.to_recommendation().action is Action.BUY

    def test_uniformly_negative_news_scores_negative(self) -> None:
        assessment = NewsAgent().assess("X", [item(Sentiment.NEGATIVE)] * 3, now=NOW)
        assert assessment.score == pytest.approx(-1.0)
        assert assessment.to_recommendation().action is Action.SELL

    def test_no_news_is_hold_with_zero_confidence(self) -> None:
        rec = NewsAgent().assess("X", [], now=NOW).to_recommendation()
        assert rec.action is Action.HOLD
        assert rec.confidence == 0.0

    def test_mixed_coverage_is_flagged(self) -> None:
        assessment = NewsAgent().assess(
            "X", [item(Sentiment.POSITIVE), item(Sentiment.NEGATIVE)], now=NOW
        )
        assert any("mixed coverage" in c for c in assessment.concerns)


class TestTimeDecay:
    def test_stale_news_counts_for_less_than_fresh_news(self) -> None:
        """Without decay, a three-week-old downgrade shouts as loudly as today's beat."""
        agent = NewsAgent(half_life_days=3.0)

        fresh_bad_stale_good = agent.assess(
            "X",
            [item(Sentiment.NEGATIVE, days_ago=0), item(Sentiment.POSITIVE, days_ago=21)],
            now=NOW,
        )
        assert fresh_bad_stale_good.score < -0.8  # the old good news barely registers

    def test_one_half_life_halves_the_weight(self) -> None:
        agent = NewsAgent(half_life_days=3.0)
        # A positive item at 3 days (weight 0.5) against a negative one today
        # (weight 1.0) -> (0.5 - 1.0) / 1.5 = -0.333
        assessment = agent.assess(
            "X",
            [item(Sentiment.POSITIVE, days_ago=3.0), item(Sentiment.NEGATIVE, days_ago=0.0)],
            now=NOW,
        )
        assert assessment.score == pytest.approx(-1 / 3, abs=0.01)


class TestCategoryWeighting:
    def test_earnings_outweighs_a_sector_thinkpiece(self) -> None:
        agent = NewsAgent()
        assessment = agent.assess(
            "X",
            [
                item(Sentiment.POSITIVE, category=NewsCategory.EARNINGS),
                item(Sentiment.NEGATIVE, category=NewsCategory.SECTOR),
            ],
            now=NOW,
        )
        # 1.5 positive vs 0.7 negative -> net positive.
        assert assessment.score > 0

    def test_headlines_are_ranked_by_impact(self) -> None:
        assessment = NewsAgent().assess(
            "X",
            [
                item(Sentiment.POSITIVE, category=NewsCategory.OTHER, headline="minor"),
                item(Sentiment.POSITIVE, category=NewsCategory.EARNINGS, headline="big"),
            ],
            now=NOW,
        )
        assert "big" in assessment.headlines[0]


class TestConviction:
    def test_a_single_article_cannot_reach_high_conviction(self) -> None:
        """One article is an anecdote."""
        rec = (
            NewsAgent()
            .assess("X", [item(Sentiment.POSITIVE, category=NewsCategory.EARNINGS)], now=NOW)
            .to_recommendation()
        )
        assert rec.conviction is not Conviction.HIGH

    def test_three_corroborating_articles_can(self) -> None:
        rec = (
            NewsAgent()
            .assess(
                "X", [item(Sentiment.POSITIVE, category=NewsCategory.EARNINGS)] * 3, now=NOW
            )
            .to_recommendation()
        )
        assert rec.conviction is Conviction.HIGH


class TestMarketContext:
    def test_risk_off_needs_two_stress_signals(self) -> None:
        one = MarketContext(as_of=NOW, india_vix=25.0, nifty_change_pct=0.3)
        two = MarketContext(as_of=NOW, india_vix=25.0, nifty_change_pct=-1.8)

        assert not one.risk_off
        assert two.risk_off

    def test_rbi_day_is_called_out(self) -> None:
        notes = MarketContextAgent().assess(MarketContext(as_of=NOW, rbi_event_today=True))
        assert any("RBI policy today" in n for n in notes)

    def test_crude_spike_names_the_sectors_it_hurts(self) -> None:
        notes = MarketContextAgent().assess(MarketContext(as_of=NOW, crude_change_pct=8.0))
        assert any("airlines" in n for n in notes)

    def test_weak_rupee_names_both_sides(self) -> None:
        notes = MarketContextAgent().assess(MarketContext(as_of=NOW, usd_inr_change_pct=0.9))
        assert any("IT and pharma" in n for n in notes)

    def test_a_calm_market_produces_no_notes(self) -> None:
        notes = MarketContextAgent().assess(
            MarketContext(as_of=NOW, india_vix=12.0, nifty_change_pct=0.2)
        )
        assert notes == []


class TestProviderPort:
    def test_the_unwired_provider_fails_loudly(self) -> None:
        with pytest.raises(ProviderNotConfiguredError, match="no news adapter"):
            NewsAgent().analyze("RELIANCE")
