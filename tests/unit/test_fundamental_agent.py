"""Fundamental agent: the scoring is real, so it gets real tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.agents import Action, Conviction, FundamentalAgent, FundamentalSnapshot
from app.agents.providers import ProviderNotConfiguredError

AGENT = FundamentalAgent()


def excellent() -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol="GOODCO",
        pe=18.0,
        pb=3.0,
        industry_pe=25.0,
        roce=28.0,
        roe=24.0,
        debt_to_equity=0.15,
        interest_coverage=20.0,
        operating_cash_flow=110.0,
        net_profit=100.0,
        revenue_growth_yoy=22.0,
        profit_growth_yoy=25.0,
        promoter_holding=62.0,
        promoter_pledge=0.0,
        promoter_holding_change=0.0,
        fii_holding=18.0,
    )


class TestScoring:
    def test_a_high_quality_company_scores_well(self) -> None:
        score = AGENT.score(excellent())
        assert score.composite > 0.7
        assert score.red_flags == []
        assert score.coverage > 0.8
        assert score.to_recommendation().action is Action.BUY

    def test_a_leveraged_shrinking_company_scores_badly(self) -> None:
        score = AGENT.score(
            FundamentalSnapshot(
                symbol="BADCO",
                pe=60.0,
                pb=9.0,
                roce=4.0,
                roe=2.0,
                debt_to_equity=3.5,
                interest_coverage=0.8,
                operating_cash_flow=10.0,
                net_profit=100.0,
                revenue_growth_yoy=-12.0,
                profit_growth_yoy=-30.0,
                promoter_holding=18.0,
                promoter_pledge=60.0,
            )
        )
        assert score.composite < 0.25
        assert score.red_flags
        assert score.to_recommendation().action is Action.SELL


class TestRedFlags:
    def test_pledged_promoter_stake_is_a_red_flag(self) -> None:
        score = AGENT.score(
            FundamentalSnapshot(symbol="X", promoter_holding=55.0, promoter_pledge=40.0)
        )
        assert any("pledged" in f for f in score.red_flags)

    def test_promoters_selling_down_is_a_red_flag(self) -> None:
        score = AGENT.score(FundamentalSnapshot(symbol="X", promoter_holding_change=-4.0))
        assert any("cut their stake" in f for f in score.red_flags)

    def test_poor_cash_conversion_is_a_red_flag(self) -> None:
        """Profit that never becomes cash is how accounting profit is manufactured."""
        score = AGENT.score(
            FundamentalSnapshot(symbol="X", operating_cash_flow=20.0, net_profit=100.0)
        )
        assert any("cash conversion" in f for f in score.red_flags)

    def test_a_red_flag_overrides_an_otherwise_excellent_score(self) -> None:
        """Great ratios do not survive an 80%-pledged promoter stake."""
        clean = AGENT.score(excellent())
        flagged = AGENT.score(replace(excellent(), promoter_pledge=80.0))

        assert clean.to_recommendation().action is Action.BUY
        assert flagged.composite > 0.6  # the ratios are still good
        assert flagged.to_recommendation().action is Action.SELL  # and it does not matter


class TestCoverage:
    def test_missing_data_lowers_coverage_not_the_score(self) -> None:
        """An absent ROCE must not be scored as a ROCE of zero."""
        thin = AGENT.score(FundamentalSnapshot(symbol="X", roce=25.0, roe=22.0))
        assert thin.composite > 0.9  # what we know is excellent
        assert thin.coverage < 0.3  # but we know almost nothing

    def test_thin_coverage_caps_conviction(self) -> None:
        rec = AGENT.score(
            FundamentalSnapshot(symbol="X", roce=30.0, roe=30.0)
        ).to_recommendation()
        assert rec.conviction is Conviction.LOW

    def test_an_empty_snapshot_is_neutral_not_negative(self) -> None:
        score = AGENT.score(FundamentalSnapshot(symbol="X"))
        assert score.composite == pytest.approx(0.5)
        assert score.to_recommendation().action is Action.HOLD


class TestProviderPort:
    def test_the_unwired_provider_fails_loudly(self) -> None:
        """It must never quietly return a made-up balance sheet."""
        with pytest.raises(ProviderNotConfiguredError, match="no fundamentals adapter"):
            FundamentalAgent().analyze("RELIANCE")

    def test_a_custom_provider_is_used(self) -> None:
        class Fake:
            def snapshot(self, symbol: str) -> FundamentalSnapshot:
                return FundamentalSnapshot(symbol=symbol, roce=30.0, roe=28.0)

        score = FundamentalAgent(provider=Fake()).analyze("TCS")
        assert score.symbol == "TCS"
        assert score.composite > 0.9
