"""Portfolio agent: performance and concentration analytics.

Pure computation over an equity curve and a trade log. No broker, no DB — the
service layer supplies the data, this decides what it means.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252


@dataclass(frozen=True, slots=True)
class Holding:
    symbol: str
    quantity: int
    avg_price: float
    last_price: float
    sector: str = "unknown"

    @property
    def value(self) -> float:
        return self.quantity * self.last_price

    @property
    def pnl(self) -> float:
        return self.quantity * (self.last_price - self.avg_price)

    @property
    def pnl_pct(self) -> float:
        cost = self.quantity * self.avg_price
        return (self.pnl / cost * 100.0) if cost else 0.0


@dataclass(frozen=True, slots=True)
class PortfolioReport:
    equity: float
    invested: float
    cash: float
    total_pnl: float

    cagr: float | None
    max_drawdown: float  # negative, e.g. -0.183 for -18.3%
    current_drawdown: float
    sharpe: float | None
    sortino: float | None
    volatility: float | None  # annualised

    win_ratio: float | None
    profit_factor: float | None
    trade_count: int

    allocation: dict[str, float] = field(default_factory=dict)  # symbol -> % of equity
    sector_exposure: dict[str, float] = field(default_factory=dict)
    concentration: float = 0.0  # HHI, 0 = perfectly diversified, 1 = all in one name
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        sharpe = f"{self.sharpe:.2f}" if self.sharpe is not None else "n/a"
        cagr = f"{self.cagr:.1%}" if self.cagr is not None else "n/a"
        return (
            f"Equity ₹{self.equity:,.0f} | CAGR {cagr} | Sharpe {sharpe} | "
            f"MaxDD {self.max_drawdown:.1%} | {self.trade_count} trades"
        )


class PortfolioAgent:
    """Computes the standard performance suite, and flags concentration.

    A note on Sharpe: it punishes upside volatility exactly as hard as downside,
    which is why Sortino is reported alongside it rather than instead of it. A
    strategy with violent winning months and shallow losing ones looks mediocre
    on Sharpe and excellent on Sortino, and the second reading is the useful one.
    """

    def __init__(
        self,
        risk_free_rate: float = 0.065,  # ~India 10Y; annual, not daily
        max_position_pct: float = 25.0,
        max_sector_pct: float = 40.0,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.max_position_pct = max_position_pct
        self.max_sector_pct = max_sector_pct

    def report(
        self,
        equity_curve: pd.Series,
        holdings: list[Holding] | None = None,
        trades: pd.DataFrame | None = None,
        cash: float = 0.0,
    ) -> PortfolioReport:
        holdings = holdings or []
        if equity_curve.empty:
            raise ValueError("equity curve is empty")

        equity = float(equity_curve.iloc[-1])
        returns = equity_curve.pct_change().dropna()

        invested = sum(h.value for h in holdings)
        total_pnl = sum(h.pnl for h in holdings)

        allocation = (
            {h.symbol: round(h.value / equity * 100.0, 2) for h in holdings} if equity else {}
        )

        sectors: dict[str, float] = {}
        for h in holdings:
            sectors[h.sector] = sectors.get(h.sector, 0.0) + h.value
        sector_exposure = (
            {k: round(v / equity * 100.0, 2) for k, v in sectors.items()} if equity else {}
        )

        warnings: list[str] = []
        for symbol, pct in allocation.items():
            if pct > self.max_position_pct:
                warnings.append(
                    f"{symbol} is {pct:.1f}% of equity, over the "
                    f"{self.max_position_pct:.0f}% single-name limit"
                )
        for sector, pct in sector_exposure.items():
            if pct > self.max_sector_pct:
                warnings.append(
                    f"{sector} is {pct:.1f}% of equity, over the "
                    f"{self.max_sector_pct:.0f}% sector limit"
                )

        win_ratio, profit_factor, trade_count = self._trade_stats(trades)

        return PortfolioReport(
            equity=round(equity, 2),
            invested=round(invested, 2),
            cash=round(cash, 2),
            total_pnl=round(total_pnl, 2),
            cagr=self.cagr(equity_curve),
            max_drawdown=self.max_drawdown(equity_curve),
            current_drawdown=self.current_drawdown(equity_curve),
            sharpe=self.sharpe(returns),
            sortino=self.sortino(returns),
            volatility=self.volatility(returns),
            win_ratio=win_ratio,
            profit_factor=profit_factor,
            trade_count=trade_count,
            allocation=allocation,
            sector_exposure=sector_exposure,
            concentration=self.concentration(allocation),
            warnings=warnings,
        )

    # --- performance -------------------------------------------------------
    def cagr(self, equity_curve: pd.Series) -> float | None:
        if len(equity_curve) < 2:
            return None
        start, end = float(equity_curve.iloc[0]), float(equity_curve.iloc[-1])
        if start <= 0 or end <= 0:
            return None

        if isinstance(equity_curve.index, pd.DatetimeIndex):
            days = (equity_curve.index[-1] - equity_curve.index[0]).days
            years = days / 365.25
        else:
            years = len(equity_curve) / TRADING_DAYS

        if years <= 0:
            return None
        return float((end / start) ** (1.0 / years) - 1.0)

    def max_drawdown(self, equity_curve: pd.Series) -> float:
        peak = equity_curve.cummax()
        return float((equity_curve / peak - 1.0).min())

    def current_drawdown(self, equity_curve: pd.Series) -> float:
        peak = float(equity_curve.cummax().iloc[-1])
        return float(equity_curve.iloc[-1] / peak - 1.0) if peak else 0.0

    def sharpe(self, returns: pd.Series, periods: int = TRADING_DAYS) -> float | None:
        if len(returns) < 2:
            return None
        std = returns.std(ddof=1)
        if np.isnan(std) or np.isclose(std, 0.0):
            return None
        excess = returns.mean() - self.risk_free_rate / periods
        return float(excess / std * np.sqrt(periods))

    def sortino(self, returns: pd.Series, periods: int = TRADING_DAYS) -> float | None:
        """Like Sharpe, but only downside deviation counts against you."""
        if len(returns) < 2:
            return None
        target = self.risk_free_rate / periods
        downside = returns[returns < target] - target
        if downside.empty:
            return None
        # Denominator is the full period count, not just the losing ones —
        # otherwise a strategy with two bad days looks infinitely good.
        downside_dev = np.sqrt((downside**2).sum() / len(returns))
        if np.isclose(downside_dev, 0.0):
            return None
        return float((returns.mean() - target) / downside_dev * np.sqrt(periods))

    def volatility(self, returns: pd.Series, periods: int = TRADING_DAYS) -> float | None:
        if len(returns) < 2:
            return None
        return float(returns.std(ddof=1) * np.sqrt(periods))

    def concentration(self, allocation: dict[str, float]) -> float:
        """Herfindahl-Hirschman index over position weights.

        1.0 = the entire book is one name. Below ~0.15 is genuinely diversified.
        """
        if not allocation:
            return 0.0
        total = sum(allocation.values())
        if total <= 0:
            return 0.0
        return round(sum((pct / total) ** 2 for pct in allocation.values()), 4)

    # --- trades ------------------------------------------------------------
    def _trade_stats(
        self, trades: pd.DataFrame | None
    ) -> tuple[float | None, float | None, int]:
        if trades is None or trades.empty or "pnl" not in trades.columns:
            return None, None, 0

        pnl = trades["pnl"].astype("float64")
        count = len(pnl)

        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]

        win_ratio = float(len(wins) / count) if count else None

        gross_loss = float(-losses.sum())
        profit_factor = (
            float(wins.sum() / gross_loss)
            if gross_loss > 0
            else (float("inf") if wins.sum() > 0 else None)
        )

        return win_ratio, profit_factor, count
