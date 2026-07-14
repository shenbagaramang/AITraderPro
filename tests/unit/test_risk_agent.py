"""Risk agent tests. The maths here is the part that loses real money if wrong."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.agents import Action, Position, RiskAgent, RiskLimits
from tests.fixtures import make_ohlcv, trending

EQUITY = 1_000_000.0


class TestSizing:
    def test_position_size_is_risk_budget_over_risk_per_unit(self) -> None:
        agent = RiskAgent(RiskLimits(risk_per_trade_pct=1.0, max_position_pct=100.0))
        # 1% of 10L = 10,000 budget. Stop is 5 away. -> 2,000 units.
        result = agent.assess("INFY", Action.BUY, entry=100.0, stop_loss=95.0, equity=EQUITY)

        assert result.approved
        assert result.quantity == 2000
        assert result.risk_amount == pytest.approx(10_000.0)
        assert result.risk_pct_of_equity == pytest.approx(1.0)

    def test_wider_stop_means_smaller_position(self) -> None:
        """The invariant that makes stop placement honest: a wider stop cannot
        buy you a bigger position."""
        agent = RiskAgent(RiskLimits(max_position_pct=100.0))
        tight = agent.assess("X", Action.BUY, 100.0, 98.0, EQUITY)
        wide = agent.assess("X", Action.BUY, 100.0, 90.0, EQUITY)

        assert tight.quantity > wide.quantity
        # But the money at risk is identical either way. That is the whole point.
        assert tight.risk_amount == pytest.approx(wide.risk_amount, rel=0.01)

    def test_exposure_cap_binds_before_risk_cap(self) -> None:
        agent = RiskAgent(RiskLimits(risk_per_trade_pct=5.0, max_position_pct=10.0))
        # Risk allows 50,000/1 = 50,000 units; exposure allows 100,000/100 = 1,000.
        result = agent.assess("X", Action.BUY, entry=100.0, stop_loss=99.0, equity=EQUITY)

        assert result.quantity == 1000
        assert any("capped by" in n for n in result.notes)

    def test_lot_size_rounds_down_never_up(self) -> None:
        """Rounding up would silently breach the limit the agent exists to enforce."""
        agent = RiskAgent(RiskLimits(risk_per_trade_pct=1.0, max_position_pct=100.0))
        result = agent.assess(
            "NIFTY", Action.BUY, entry=100.0, stop_loss=97.0, equity=EQUITY, lot_size=50
        )
        # 10,000 / 3 = 3,333 -> floor to 3,300 (66 lots)
        assert result.quantity == 3300
        assert result.quantity % 50 == 0
        assert result.risk_amount <= EQUITY * 0.01

    def test_short_position_sizes_off_a_stop_above_entry(self) -> None:
        agent = RiskAgent(RiskLimits(max_position_pct=100.0))
        result = agent.assess("X", Action.SELL, entry=100.0, stop_loss=105.0, equity=EQUITY)
        assert result.approved
        assert result.quantity == 2000


class TestVetoes:
    def test_stop_on_the_wrong_side_of_a_buy_is_rejected(self) -> None:
        result = RiskAgent().assess(
            "X", Action.BUY, entry=100.0, stop_loss=105.0, equity=EQUITY
        )
        assert not result.approved
        assert "above entry" in result.vetoes[0]

    def test_stop_on_the_wrong_side_of_a_sell_is_rejected(self) -> None:
        result = RiskAgent().assess(
            "X", Action.SELL, entry=100.0, stop_loss=95.0, equity=EQUITY
        )
        assert not result.approved
        assert "below entry" in result.vetoes[0]

    def test_poor_reward_risk_is_rejected(self) -> None:
        agent = RiskAgent(RiskLimits(min_reward_risk=2.0, max_position_pct=100.0))
        # Risk 5, reward 5 -> R:R of 1.0, below the 2.0 floor.
        result = agent.assess(
            "X", Action.BUY, entry=100.0, stop_loss=95.0, equity=EQUITY, target=105.0
        )
        assert not result.approved
        assert any("reward:risk" in v for v in result.vetoes)

    def test_good_reward_risk_passes(self) -> None:
        agent = RiskAgent(RiskLimits(min_reward_risk=2.0, max_position_pct=100.0))
        result = agent.assess(
            "X", Action.BUY, entry=100.0, stop_loss=95.0, equity=EQUITY, target=115.0
        )
        assert result.approved
        assert result.reward_risk == pytest.approx(3.0)

    def test_tiny_account_that_cannot_afford_one_unit_is_rejected(self) -> None:
        agent = RiskAgent(RiskLimits(risk_per_trade_pct=1.0))
        # 1% of 1,000 = 10 budget, but one unit risks 500.
        result = agent.assess("X", Action.BUY, entry=5000.0, stop_loss=4500.0, equity=1000.0)
        assert not result.approved
        assert any("sizes to zero" in v for v in result.vetoes)

    def test_max_open_positions_is_enforced(self) -> None:
        agent = RiskAgent(RiskLimits(max_open_positions=2, max_position_pct=100.0))
        held = [Position("A", 1, 1.0), Position("B", 1, 1.0)]
        result = agent.assess("C", Action.BUY, 100.0, 95.0, EQUITY, open_positions=held)
        assert not result.approved
        assert any("limit is 2" in v for v in result.vetoes)

    def test_total_exposure_cap_is_enforced(self) -> None:
        agent = RiskAgent(RiskLimits(max_portfolio_exposure_pct=50.0, max_position_pct=40.0))
        held = [Position("A", 4000, 100.0)]  # 400,000 = 40% of equity already
        result = agent.assess("B", Action.BUY, 100.0, 99.0, EQUITY, open_positions=held)
        assert not result.approved
        assert any("total exposure" in v for v in result.vetoes)

    def test_hold_cannot_be_sized(self) -> None:
        result = RiskAgent().assess("X", Action.HOLD, 100.0, 95.0, EQUITY)
        assert not result.approved

    def test_zero_equity_is_rejected(self) -> None:
        result = RiskAgent().assess("X", Action.BUY, 100.0, 95.0, equity=0.0)
        assert not result.approved


class TestCorrelation:
    def _returns(self, corr: float) -> pd.DataFrame:
        rng = np.random.default_rng(4)
        base = rng.normal(0, 0.01, 300)
        noise = rng.normal(0, 0.01, 300)
        other = corr * base + np.sqrt(max(1 - corr**2, 0)) * noise
        return pd.DataFrame({"HELD": base, "NEW": other})

    def test_highly_correlated_new_position_is_vetoed(self) -> None:
        """Five positions that move together are one position at five times size."""
        agent = RiskAgent(RiskLimits(max_correlation=0.8, max_position_pct=100.0))
        result = agent.assess(
            "NEW",
            Action.BUY,
            100.0,
            95.0,
            EQUITY,
            open_positions=[Position("HELD", 10, 100.0)],
            returns=self._returns(0.97),
        )
        assert not result.approved
        assert any("correlated" in v for v in result.vetoes)

    def test_uncorrelated_position_passes_and_is_noted(self) -> None:
        agent = RiskAgent(RiskLimits(max_correlation=0.8, max_position_pct=100.0))
        result = agent.assess(
            "NEW",
            Action.BUY,
            100.0,
            95.0,
            EQUITY,
            open_positions=[Position("HELD", 10, 100.0)],
            returns=self._returns(0.05),
        )
        assert result.approved
        assert any("correlation" in n for n in result.notes)

    def test_missing_returns_data_skips_the_check_rather_than_crashing(self) -> None:
        agent = RiskAgent(RiskLimits(max_position_pct=100.0))
        result = agent.assess(
            "NEW",
            Action.BUY,
            100.0,
            95.0,
            EQUITY,
            open_positions=[Position("HELD", 10, 100.0)],
            returns=None,
        )
        assert result.approved


class TestStops:
    def test_atr_stop_sits_below_entry_on_a_buy(self) -> None:
        assert (
            RiskAgent().atr_stop(100.0, atr_value=2.0, action=Action.BUY, multiplier=2.0)
            == 96.0
        )

    def test_atr_stop_sits_above_entry_on_a_sell(self) -> None:
        assert (
            RiskAgent().atr_stop(100.0, atr_value=2.0, action=Action.SELL, multiplier=2.0)
            == 104.0
        )

    def test_volatile_name_gets_a_wider_stop(self) -> None:
        agent = RiskAgent()
        quiet = agent.atr_stop(100.0, 1.0, Action.BUY)
        volatile = agent.atr_stop(100.0, 5.0, Action.BUY)
        assert volatile < quiet

    def test_chandelier_trails_the_highest_high(self) -> None:
        df = make_ohlcv(trending(60, drift=1.0))
        stop = RiskAgent().chandelier_stop(
            df, atr_value=2.0, action=Action.BUY, multiplier=3.0
        )
        highest = float(df["high"].iloc[-22:].max())
        assert stop == pytest.approx(highest - 6.0)
        assert stop < float(df["close"].iloc[-1])

    def test_zero_atr_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="atr must be positive"):
            RiskAgent().atr_stop(100.0, 0.0, Action.BUY)


class TestLimitsValidation:
    def test_impossible_risk_pct_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="risk_per_trade_pct"):
            RiskLimits(risk_per_trade_pct=0.0)
