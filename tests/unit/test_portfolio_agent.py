"""Portfolio agent tests, asserted against closed-form values."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.agents import Holding, PortfolioAgent


def curve(values: list[float], dates: bool = True) -> pd.Series:
    index = pd.date_range("2024-01-01", periods=len(values), freq="D") if dates else None
    return pd.Series(values, index=index, dtype="float64")


class TestPerformance:
    def test_cagr_over_exactly_one_year(self) -> None:
        index = pd.to_datetime(["2024-01-01", "2025-01-01"])
        equity = pd.Series([100_000.0, 120_000.0], index=index)
        # 20% over ~1.0 year (365/365.25) -> a hair above 20%.
        assert PortfolioAgent().cagr(equity) == pytest.approx(0.20, abs=0.001)

    def test_cagr_over_two_years_annualises(self) -> None:
        index = pd.to_datetime(["2023-01-01", "2025-01-01"])
        equity = pd.Series([100.0, 144.0], index=index)
        # 44% total over 2 years -> 20% a year, not 22%.
        assert PortfolioAgent().cagr(equity) == pytest.approx(0.20, abs=0.002)

    def test_max_drawdown_measures_peak_to_trough(self) -> None:
        equity = curve([100.0, 120.0, 90.0, 110.0])
        # Peak 120, trough 90 -> -25%.
        assert PortfolioAgent().max_drawdown(equity) == pytest.approx(-0.25)

    def test_max_drawdown_is_zero_on_a_monotonic_rise(self) -> None:
        assert PortfolioAgent().max_drawdown(curve([100.0, 110.0, 120.0])) == pytest.approx(
            0.0
        )

    def test_current_drawdown_recovers_to_zero_at_a_new_high(self) -> None:
        agent = PortfolioAgent()
        assert agent.current_drawdown(curve([100.0, 80.0, 130.0])) == pytest.approx(0.0)
        assert agent.current_drawdown(curve([100.0, 130.0, 104.0])) == pytest.approx(-0.20)

    def test_sharpe_matches_the_closed_form(self) -> None:
        agent = PortfolioAgent(risk_free_rate=0.0)
        rng = np.random.default_rng(2)
        returns = pd.Series(rng.normal(0.001, 0.01, 500))

        expected = returns.mean() / returns.std(ddof=1) * np.sqrt(252)
        assert agent.sharpe(returns) == pytest.approx(expected)

    def test_sortino_exceeds_sharpe_when_the_upside_is_the_volatile_side(self) -> None:
        """The reason both are reported: Sharpe punishes good volatility too."""
        agent = PortfolioAgent(risk_free_rate=0.0)
        # Big winners, small consistent losers.
        returns = pd.Series([0.08, -0.005, 0.09, -0.004, 0.07, -0.005] * 20)

        assert agent.sortino(returns) > agent.sharpe(returns)

    def test_sortino_is_none_when_nothing_ever_lost(self) -> None:
        agent = PortfolioAgent(risk_free_rate=0.0)
        assert agent.sortino(pd.Series([0.01] * 50)) is None

    def test_sharpe_is_none_on_zero_variance(self) -> None:
        assert PortfolioAgent().sharpe(pd.Series([0.01] * 50)) is None

    def test_volatility_annualises_daily_stdev(self) -> None:
        returns = pd.Series(np.random.default_rng(1).normal(0, 0.01, 300))
        expected = returns.std(ddof=1) * np.sqrt(252)
        assert PortfolioAgent().volatility(returns) == pytest.approx(expected)


class TestTradeStats:
    def test_win_ratio_and_profit_factor(self) -> None:
        trades = pd.DataFrame({"pnl": [100.0, -50.0, 200.0, -25.0, 75.0]})
        report = PortfolioAgent().report(curve([100.0, 110.0]), trades=trades)

        assert report.trade_count == 5
        assert report.win_ratio == pytest.approx(3 / 5)
        # Gross profit 375, gross loss 75 -> 5.0
        assert report.profit_factor == pytest.approx(5.0)

    def test_a_high_win_ratio_can_still_be_a_losing_system(self) -> None:
        """9 small wins, 1 huge loss. Win ratio flatters; profit factor tells the truth."""
        trades = pd.DataFrame({"pnl": [10.0] * 9 + [-500.0]})
        report = PortfolioAgent().report(curve([100.0, 90.0]), trades=trades)

        assert report.win_ratio == pytest.approx(0.9)
        assert report.profit_factor is not None
        assert report.profit_factor < 1.0

    def test_no_trades_reports_none_not_zero(self) -> None:
        report = PortfolioAgent().report(curve([100.0, 110.0]))
        assert report.trade_count == 0
        assert report.win_ratio is None


class TestConcentration:
    def test_hhi_of_a_single_name_book_is_one(self) -> None:
        assert PortfolioAgent().concentration({"A": 100.0}) == pytest.approx(1.0)

    def test_hhi_falls_as_the_book_diversifies(self) -> None:
        agent = PortfolioAgent()
        four = agent.concentration({"A": 25.0, "B": 25.0, "C": 25.0, "D": 25.0})
        ten = agent.concentration(dict.fromkeys("ABCDEFGHIJ", 10.0))

        assert four == pytest.approx(0.25)
        assert ten == pytest.approx(0.10)
        assert ten < four

    def test_oversized_position_raises_a_warning(self) -> None:
        agent = PortfolioAgent(max_position_pct=25.0)
        holdings = [
            Holding("BIGCO", 600, 1000.0, 1000.0, sector="it"),  # 600k of 1M = 60%
            Holding("SMALLCO", 100, 1000.0, 1000.0, sector="fmcg"),
        ]
        report = agent.report(curve([1_000_000.0, 1_000_000.0]), holdings=holdings)

        assert any("BIGCO" in w and "60.0%" in w for w in report.warnings)

    def test_sector_concentration_raises_a_warning(self) -> None:
        agent = PortfolioAgent(max_position_pct=100.0, max_sector_pct=40.0)
        holdings = [
            Holding("TCS", 200, 1000.0, 1000.0, sector="it"),
            Holding("INFY", 200, 1000.0, 1000.0, sector="it"),
            Holding("WIPRO", 100, 1000.0, 1000.0, sector="it"),
        ]
        report = agent.report(curve([1_000_000.0, 1_000_000.0]), holdings=holdings)

        assert report.sector_exposure["it"] == pytest.approx(50.0)
        assert any("it is 50.0%" in w for w in report.warnings)


class TestReport:
    def test_holding_pnl_arithmetic(self) -> None:
        h = Holding("X", 100, avg_price=50.0, last_price=60.0)
        assert h.value == pytest.approx(6000.0)
        assert h.pnl == pytest.approx(1000.0)
        assert h.pnl_pct == pytest.approx(20.0)

    def test_empty_equity_curve_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            PortfolioAgent().report(pd.Series([], dtype="float64"))

    def test_summary_is_human_readable(self) -> None:
        equity = curve(list(np.linspace(100_000, 130_000, 300)))
        report = PortfolioAgent().report(equity)
        assert "Equity" in report.summary()
        assert "Sharpe" in report.summary()
