"""Risk agent: sizes the position, sets the stop, and holds the veto.

This is the only agent with the power to say *no*. Every other agent produces an
opinion; this one produces a constraint. A trade that the technical agent loves
and the risk agent rejects does not happen — and that asymmetry is deliberate,
because the failure mode that ends accounts is not missing a good trade, it is
taking a good trade too large.

Pure computation: inputs in, RiskAssessment out. No broker, no DB.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.agents.base import Action


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """The account's rules. Breaching any of these vetoes the trade."""

    risk_per_trade_pct: float = 1.0  # % of equity risked if the stop is hit
    max_position_pct: float = 20.0  # % of equity in any one symbol
    max_portfolio_exposure_pct: float = 100.0
    max_correlation: float = 0.80  # vs any existing holding
    min_reward_risk: float = 1.5
    max_open_positions: int = 10

    def __post_init__(self) -> None:
        if not 0 < self.risk_per_trade_pct <= 100:
            raise ValueError("risk_per_trade_pct must be in (0, 100]")
        if not 0 < self.max_position_pct <= 100:
            raise ValueError("max_position_pct must be in (0, 100]")
        if self.min_reward_risk <= 0:
            raise ValueError("min_reward_risk must be positive")


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: int
    entry_price: float

    @property
    def value(self) -> float:
        return self.quantity * self.entry_price


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    symbol: str
    approved: bool
    action: Action
    quantity: int
    entry: float
    stop_loss: float
    target: float | None
    risk_amount: float  # currency at risk if the stop fills
    risk_pct_of_equity: float
    position_value: float
    reward_risk: float | None
    vetoes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def summary(self) -> str:
        if not self.approved:
            return f"{self.symbol}: REJECTED — {'; '.join(self.vetoes)}"
        rr = f"{self.reward_risk:.2f}" if self.reward_risk else "n/a"
        return (
            f"{self.symbol}: {self.action.value} {self.quantity} @ {self.entry:.2f}, "
            f"stop {self.stop_loss:.2f}, risk ₹{self.risk_amount:,.0f} "
            f"({self.risk_pct_of_equity:.2f}% of equity), R:R {rr}"
        )


class RiskAgent:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()

    # --- stops -------------------------------------------------------------
    def atr_stop(
        self, entry: float, atr_value: float, action: Action, multiplier: float = 2.0
    ) -> float:
        """Volatility-scaled stop. A fixed-percent stop is wrong on both ends:
        too tight on a volatile name, needlessly wide on a quiet one."""
        if atr_value <= 0:
            raise ValueError("atr must be positive")
        distance = multiplier * atr_value
        return entry - distance if action is Action.BUY else entry + distance

    def chandelier_stop(
        self,
        df: pd.DataFrame,
        atr_value: float,
        action: Action,
        lookback: int = 22,
        multiplier: float = 3.0,
    ) -> float:
        """Trailing stop anchored to the highest high (or lowest low) since entry.

        Ratchets in the direction of the trade and never loosens, which is the
        whole point — a trailing stop that can widen is not a stop.
        """
        window = df.iloc[-lookback:]
        if action is Action.BUY:
            return float(window["high"].max()) - multiplier * atr_value
        return float(window["low"].min()) + multiplier * atr_value

    # --- sizing ------------------------------------------------------------
    def assess(
        self,
        symbol: str,
        action: Action,
        entry: float,
        stop_loss: float,
        equity: float,
        *,
        target: float | None = None,
        lot_size: int = 1,
        open_positions: list[Position] | None = None,
        returns: pd.DataFrame | None = None,
    ) -> RiskAssessment:
        """Size the trade and decide whether it may proceed at all.

        ``returns`` is an optional frame of daily returns keyed by symbol, used
        for the correlation check against what is already held.
        """
        open_positions = open_positions or []
        vetoes: list[str] = []
        notes: list[str] = []

        if action is Action.HOLD:
            return self._reject(
                symbol, action, entry, stop_loss, target, ["no directional action to size"]
            )
        if equity <= 0:
            return self._reject(
                symbol,
                action,
                entry,
                stop_loss,
                target,
                ["account equity is zero or negative"],
            )
        if entry <= 0:
            return self._reject(
                symbol, action, entry, stop_loss, target, ["entry price must be positive"]
            )

        # A stop on the wrong side of entry is not a stop, it is a target.
        if action is Action.BUY and stop_loss >= entry:
            return self._reject(
                symbol,
                action,
                entry,
                stop_loss,
                target,
                [f"stop {stop_loss:.2f} is at or above entry {entry:.2f} on a buy"],
            )
        if action is Action.SELL and stop_loss <= entry:
            return self._reject(
                symbol,
                action,
                entry,
                stop_loss,
                target,
                [f"stop {stop_loss:.2f} is at or below entry {entry:.2f} on a sell"],
            )

        risk_per_unit = abs(entry - stop_loss)
        if risk_per_unit == 0:
            return self._reject(
                symbol,
                action,
                entry,
                stop_loss,
                target,
                ["stop equals entry: risk per unit is zero"],
            )

        # Reward:risk, when a target is supplied.
        reward_risk: float | None = None
        if target is not None:
            reward = (target - entry) if action is Action.BUY else (entry - target)
            reward_risk = reward / risk_per_unit
            if reward_risk < self.limits.min_reward_risk:
                vetoes.append(
                    f"reward:risk {reward_risk:.2f} is below the "
                    f"{self.limits.min_reward_risk} minimum — the trade is not worth "
                    "its own stop"
                )

        # Two independent caps. The binding one wins.
        budget = equity * self.limits.risk_per_trade_pct / 100.0
        qty_by_risk = math.floor(budget / risk_per_unit)
        qty_by_exposure = math.floor((equity * self.limits.max_position_pct / 100.0) / entry)
        quantity = min(qty_by_risk, qty_by_exposure)

        if qty_by_exposure < qty_by_risk:
            notes.append(
                f"size capped by the {self.limits.max_position_pct}% position limit, "
                f"not by risk ({qty_by_exposure} vs {qty_by_risk} units)"
            )

        # Round down to a whole lot. Rounding up would silently exceed the limit.
        if lot_size > 1:
            quantity = (quantity // lot_size) * lot_size

        if quantity <= 0:
            vetoes.append(
                f"position sizes to zero: risking {self.limits.risk_per_trade_pct}% of "
                f"₹{equity:,.0f} allows ₹{budget:,.0f}, but one unit risks "
                f"₹{risk_per_unit:.2f}"
                + (f" and the lot size is {lot_size}" if lot_size > 1 else "")
            )

        position_value = quantity * entry
        risk_amount = quantity * risk_per_unit

        # Portfolio-level caps.
        if len(open_positions) >= self.limits.max_open_positions:
            vetoes.append(
                f"already holding {len(open_positions)} positions, "
                f"limit is {self.limits.max_open_positions}"
            )

        held_value = sum(p.value for p in open_positions)
        total_exposure_pct = (held_value + position_value) / equity * 100.0
        if total_exposure_pct > self.limits.max_portfolio_exposure_pct:
            vetoes.append(
                f"total exposure would reach {total_exposure_pct:.0f}% of equity, "
                f"over the {self.limits.max_portfolio_exposure_pct:.0f}% cap"
            )

        # Correlation: five positions that all move together are one position
        # with five times the size, and the risk-per-trade limit is an illusion.
        correlation = self._max_correlation(symbol, open_positions, returns)
        if correlation is not None:
            peer, value = correlation
            if value > self.limits.max_correlation:
                vetoes.append(
                    f"{value:.2f} correlated with {peer}, over the "
                    f"{self.limits.max_correlation} limit — this is not "
                    "diversification, it is the same bet twice"
                )
            else:
                notes.append(f"highest correlation with holdings: {value:.2f} ({peer})")

        return RiskAssessment(
            symbol=symbol,
            approved=not vetoes,
            action=action,
            quantity=quantity if not vetoes else 0,
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            risk_amount=round(risk_amount, 2) if not vetoes else 0.0,
            risk_pct_of_equity=round(risk_amount / equity * 100.0, 4) if not vetoes else 0.0,
            position_value=round(position_value, 2) if not vetoes else 0.0,
            reward_risk=round(reward_risk, 4) if reward_risk is not None else None,
            vetoes=vetoes,
            notes=notes,
            metrics={
                "risk_per_unit": round(risk_per_unit, 4),
                "qty_by_risk": float(qty_by_risk),
                "qty_by_exposure": float(qty_by_exposure),
                "total_exposure_pct": round(total_exposure_pct, 2),
            },
        )

    # --- internals ---------------------------------------------------------
    def _max_correlation(
        self,
        symbol: str,
        open_positions: list[Position],
        returns: pd.DataFrame | None,
    ) -> tuple[str, float] | None:
        if returns is None or not open_positions or symbol not in returns.columns:
            return None

        peers = [p.symbol for p in open_positions if p.symbol in returns.columns]
        if not peers:
            return None

        correlations = {
            peer: returns[symbol].corr(returns[peer]) for peer in peers if peer != symbol
        }
        correlations = {k: v for k, v in correlations.items() if not np.isnan(v)}
        if not correlations:
            return None

        peer = max(correlations, key=lambda k: abs(correlations[k]))
        return peer, abs(float(correlations[peer]))

    def _reject(
        self,
        symbol: str,
        action: Action,
        entry: float,
        stop: float,
        target: float | None,
        vetoes: list[str],
    ) -> RiskAssessment:
        return RiskAssessment(
            symbol=symbol,
            approved=False,
            action=action,
            quantity=0,
            entry=entry,
            stop_loss=stop,
            target=target,
            risk_amount=0.0,
            risk_pct_of_equity=0.0,
            position_value=0.0,
            reward_risk=None,
            vetoes=vetoes,
        )
