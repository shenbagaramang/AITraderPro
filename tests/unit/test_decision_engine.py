"""The engine's job is mostly to say no. These tests mostly check that it does."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from app.agents import (
    FundamentalScore,
    MarketContext,
    NewsAssessment,
    Position,
    RiskLimits,
    Sentiment,
)
from app.agents.base import Action
from app.engine import DecisionEngine, DecisionOutcome, EngineConfig, MarketData
from tests.fixtures import flat, make_ohlcv, trending

EQUITY = 1_000_000.0
NOW = datetime(2026, 7, 13, tzinfo=UTC)


def bullish_candles():
    rng = np.random.default_rng(5)
    closes = np.r_[flat(100, 100.0, noise=0.5), 100.0 + np.cumsum(rng.uniform(0.5, 1.5, 40))]
    return make_ohlcv(closes, np.r_[np.full(100, 1e5), np.linspace(2e5, 5e5, 40)])


def ranging_candles():
    return make_ohlcv(flat(200, 100.0, noise=1.0))


class TestTechnicalProposes:
    def test_a_clean_uptrend_produces_a_trade(self) -> None:
        decision = DecisionEngine().decide(MarketData("TCS", bullish_candles()), equity=EQUITY)
        assert decision.outcome is DecisionOutcome.TRADE
        assert decision.action is Action.BUY
        assert decision.quantity > 0
        assert decision.stop_loss < decision.entry
        assert decision.target > decision.entry

    def test_target_sits_at_2R_by_construction(self) -> None:
        decision = DecisionEngine().decide(MarketData("TCS", bullish_candles()), equity=EQUITY)
        risk = decision.entry - decision.stop_loss
        reward = decision.target - decision.entry
        assert reward / risk == pytest.approx(2.0)

    def test_a_ranging_market_produces_no_trade(self) -> None:
        """Nothing else in the system gets a say if there is no trend to trade."""
        decision = DecisionEngine().decide(MarketData("X", ranging_candles()), equity=EQUITY)
        assert decision.outcome is DecisionOutcome.NO_TRADE
        assert any("ranging" in r for r in decision.reasons)

    def test_shorts_are_disabled_by_default(self) -> None:
        bearish = make_ohlcv(trending(200, start=300.0, drift=-1.0))
        decision = DecisionEngine().decide(MarketData("X", bearish), equity=EQUITY)

        assert decision.outcome is DecisionOutcome.NO_TRADE
        assert any("shorting is disabled" in r for r in decision.reasons)

    def test_shorts_can_be_enabled(self) -> None:
        bearish = make_ohlcv(trending(200, start=300.0, drift=-1.0))
        engine = DecisionEngine(EngineConfig(allow_shorts=True))
        decision = engine.decide(MarketData("X", bearish), equity=EQUITY)

        assert decision.action is Action.SELL
        assert decision.stop_loss > decision.entry  # a short's stop sits above

    def test_nothing_but_technical_can_originate_a_trade(self) -> None:
        """Perfect fundamentals cannot conjure a trade out of a flat chart."""
        perfect = FundamentalScore(
            symbol="X", composite=0.95, coverage=1.0, strengths=["everything is great"]
        )
        decision = DecisionEngine().decide(
            MarketData("X", ranging_candles(), fundamentals=perfect), equity=EQUITY
        )
        assert decision.outcome is DecisionOutcome.NO_TRADE


class TestFiltersVeto:
    def test_a_fundamental_red_flag_kills_a_beautiful_chart(self) -> None:
        flagged = FundamentalScore(
            symbol="TCS",
            composite=0.8,
            coverage=1.0,
            red_flags=["70% of the promoter stake is pledged"],
        )
        decision = DecisionEngine().decide(
            MarketData("TCS", bullish_candles(), fundamentals=flagged), equity=EQUITY
        )
        assert decision.outcome is DecisionOutcome.VETOED
        assert any("red flag" in v for v in decision.vetoes)

    def test_a_weak_fundamental_score_vetoes_a_long(self) -> None:
        weak = FundamentalScore(symbol="TCS", composite=0.15, coverage=0.9)
        decision = DecisionEngine().decide(
            MarketData("TCS", bullish_candles(), fundamentals=weak), equity=EQUITY
        )
        assert decision.outcome is DecisionOutcome.VETOED

    def test_contradicting_news_disqualifies_rather_than_shrinking_the_size(self) -> None:
        """The core arbitration rule. Averaging opposing high-conviction views
        produces a position nobody believes in."""
        bad_news = NewsAssessment(
            symbol="TCS",
            score=-0.9,
            item_count=5,
            dominant=Sentiment.NEGATIVE,
            headlines=["[earnings] guidance slashed"],
        )
        decision = DecisionEngine().decide(
            MarketData("TCS", bullish_candles(), news=bad_news), equity=EQUITY
        )

        assert decision.outcome is DecisionOutcome.VETOED
        assert decision.quantity == 0  # not "a smaller position"
        assert any("conflict is a reason to stay out" in v for v in decision.vetoes)

    def test_supporting_news_does_not_veto(self) -> None:
        good_news = NewsAssessment(
            symbol="TCS",
            score=0.8,
            item_count=4,
            dominant=Sentiment.POSITIVE,
            headlines=["[earnings] beat on all lines"],
        )
        decision = DecisionEngine().decide(
            MarketData("TCS", bullish_candles(), news=good_news), equity=EQUITY
        )
        assert decision.outcome is DecisionOutcome.TRADE
        assert any("news:" in r for r in decision.reasons)

    def test_a_risk_off_backdrop_vetoes_a_long(self) -> None:
        risk_off = MarketContext(
            as_of=NOW, india_vix=28.0, nifty_change_pct=-2.2, global_cues=Sentiment.NEGATIVE
        )
        decision = DecisionEngine().decide(
            MarketData("TCS", bullish_candles(), context=risk_off), equity=EQUITY
        )
        assert decision.outcome is DecisionOutcome.VETOED
        assert any("risk-off" in v for v in decision.vetoes)


class TestRiskHoldsTheLastVeto:
    def test_a_correlated_holding_vetoes_the_trade(self) -> None:
        import pandas as pd

        rng = np.random.default_rng(4)
        base = rng.normal(0, 0.01, 300)
        near_identical = 0.97 * base + np.sqrt(1 - 0.97**2) * rng.normal(0, 0.01, 300)
        returns = pd.DataFrame({"HELD": base, "TCS": near_identical})

        decision = DecisionEngine().decide(
            MarketData("TCS", bullish_candles(), returns=returns),
            equity=EQUITY,
            open_positions=[Position("HELD", 100, 500.0)],
        )
        assert decision.outcome is DecisionOutcome.VETOED
        assert any("correlated" in v for v in decision.vetoes)

    def test_an_account_too_small_to_size_the_trade_is_vetoed(self) -> None:
        decision = DecisionEngine().decide(MarketData("TCS", bullish_candles()), equity=500.0)
        assert decision.outcome is DecisionOutcome.VETOED
        assert any("sizes to zero" in v for v in decision.vetoes)

    def test_the_position_limit_caps_the_size(self) -> None:
        engine = DecisionEngine(risk_limits=RiskLimits(max_position_pct=5.0))
        decision = engine.decide(MarketData("TCS", bullish_candles()), equity=EQUITY)

        assert decision.outcome is DecisionOutcome.TRADE
        assert decision.quantity * decision.entry <= EQUITY * 0.05 + 1


class TestAudit:
    def test_every_agent_records_a_vote(self) -> None:
        decision = DecisionEngine().decide(
            MarketData(
                "TCS",
                bullish_candles(),
                fundamentals=FundamentalScore("TCS", 0.75, 0.9),
                news=NewsAssessment("TCS", 0.5, 3, Sentiment.POSITIVE),
            ),
            equity=EQUITY,
        )
        assert set(decision.agent_votes) == {"technical", "fundamental", "news", "risk"}

    def test_missing_agents_vote_no_data_rather_than_silently_agreeing(self) -> None:
        decision = DecisionEngine().decide(MarketData("TCS", bullish_candles()), equity=EQUITY)
        assert decision.agent_votes["fundamental"] == "no data"
        assert decision.agent_votes["news"] == "no data"

    def test_the_decision_serialises_for_the_order_record(self) -> None:
        """Six months later the question is not 'what did I buy' but 'what was I
        thinking'. This is the answer, and it is stored with the order."""
        decision = DecisionEngine().decide(MarketData("TCS", bullish_candles()), equity=EQUITY)
        payload = decision.to_dict()

        assert payload["outcome"] == "trade"
        assert payload["quantity"] > 0
        assert payload["reasons"]
        assert "decided_at" in payload
