"""Fundamental agent: scores a company from its financials.

The scoring here is real and fully tested. The *data* is not — see
``providers.py``. Call ``score(snapshot)`` with a snapshot you already hold, or
wire a ``FundamentalsProvider`` and call ``analyze(symbol)``.

A deliberate limitation, stated rather than hidden: this scores a company, not a
*price*. A superb business at an absurd valuation and a mediocre one at a fair
price can land on similar composite scores, which is why valuation is reported as
its own component instead of being blended away into a single number. Read the
components, not just the total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.agents.base import Action, Conviction, Recommendation

if TYPE_CHECKING:
    from app.agents.providers import FundamentalsProvider


@dataclass(frozen=True, slots=True)
class FundamentalSnapshot:
    """One point-in-time read of a company's financials.

    Every field is optional because real data is patchy, and an agent that
    crashes on a missing ROCE is an agent that never runs. Missing inputs reduce
    ``coverage`` instead, and coverage is reported so a high score built on three
    data points is not mistaken for a high score built on twelve.
    """

    symbol: str

    # Valuation
    pe: float | None = None
    pb: float | None = None
    industry_pe: float | None = None

    # Returns
    roce: float | None = None  # %
    roe: float | None = None  # %

    # Leverage and cash
    debt_to_equity: float | None = None
    interest_coverage: float | None = None
    operating_cash_flow: float | None = None  # absolute, same units as profit
    net_profit: float | None = None

    # Growth (%, year on year)
    revenue_growth_yoy: float | None = None
    profit_growth_yoy: float | None = None
    revenue_growth_qoq: float | None = None
    profit_growth_qoq: float | None = None

    # Ownership
    promoter_holding: float | None = None  # %
    promoter_pledge: float | None = None  # % of promoter stake pledged
    fii_holding: float | None = None  # %
    dii_holding: float | None = None  # %
    promoter_holding_change: float | None = None  # pp, QoQ


@dataclass(frozen=True, slots=True)
class FundamentalScore:
    symbol: str
    composite: float  # 0..1
    coverage: float  # share of inputs actually present
    components: dict[str, float] = field(default_factory=dict)
    strengths: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)

    def to_recommendation(self) -> Recommendation:
        # A red flag overrides the composite. A company can look wonderful on
        # ratios and still be one where the promoter has pledged 80% of his
        # stake, and in that case the ratios are not the story.
        if self.red_flags:
            action, conviction = Action.SELL, Conviction.MODERATE
        elif self.composite >= 0.70:
            action, conviction = Action.BUY, Conviction.HIGH
        elif self.composite >= 0.55:
            action, conviction = Action.BUY, Conviction.MODERATE
        elif self.composite <= 0.30:
            action, conviction = Action.SELL, Conviction.MODERATE
        else:
            action, conviction = Action.HOLD, Conviction.LOW

        # Thin data cannot support a confident call, whatever the score says.
        if self.coverage < 0.5:
            conviction = Conviction.LOW

        return Recommendation(
            agent="fundamental",
            symbol=self.symbol,
            action=action,
            confidence=round(abs(self.composite - 0.5) * 2, 4),
            conviction=conviction,
            explanation=self.strengths,
            concerns=self.concerns + self.red_flags,
            metrics={"composite": self.composite, "coverage": self.coverage},
        )


# Weights for the composite. Judgements, not measurements — same caveat as the
# scanner weights. Quality and leverage lead because they are what survives a
# downturn; valuation matters but a cheap bad business stays cheap.
WEIGHTS = {
    "quality": 0.30,  # ROCE, ROE
    "leverage": 0.25,  # D/E, interest coverage, cash conversion
    "growth": 0.25,  # revenue and profit growth
    "valuation": 0.20,  # PE, PB, PE vs industry
}


class FundamentalAgent:
    def __init__(self, provider: FundamentalsProvider | None = None) -> None:
        if provider is None:
            from app.agents.providers import UnconfiguredFundamentals

            provider = UnconfiguredFundamentals()
        self.provider = provider

    def analyze(self, symbol: str) -> FundamentalScore:
        """Fetch and score. Raises ProviderNotConfiguredError until an adapter exists."""
        return self.score(self.provider.snapshot(symbol))

    def score(self, snap: FundamentalSnapshot) -> FundamentalScore:
        components: dict[str, float] = {}
        strengths: list[str] = []
        concerns: list[str] = []
        red_flags: list[str] = []
        present = 0
        total = 0

        # --- Quality -------------------------------------------------------
        quality: list[float] = []
        for value, name, good, poor in (
            (snap.roce, "ROCE", 20.0, 10.0),
            (snap.roe, "ROE", 18.0, 8.0),
        ):
            total += 1
            if value is None:
                continue
            present += 1
            quality.append(self._band(value, poor, good))
            if value >= good:
                strengths.append(f"{name} {value:.1f}% — strong capital efficiency")
            elif value < poor:
                concerns.append(f"{name} {value:.1f}% — weak returns on capital")
        if quality:
            components["quality"] = sum(quality) / len(quality)

        # --- Leverage and cash ---------------------------------------------
        leverage: list[float] = []
        total += 1
        if snap.debt_to_equity is not None:
            present += 1
            leverage.append(self._band(snap.debt_to_equity, 2.0, 0.3, invert=True))
            if snap.debt_to_equity > 2.0:
                red_flags.append(
                    f"debt/equity {snap.debt_to_equity:.2f} — the balance sheet is "
                    "the thesis now, not the business"
                )
            elif snap.debt_to_equity < 0.3:
                strengths.append(f"debt/equity {snap.debt_to_equity:.2f} — near debt-free")

        total += 1
        if snap.interest_coverage is not None:
            present += 1
            leverage.append(self._band(snap.interest_coverage, 1.5, 8.0))
            if snap.interest_coverage < 1.5:
                red_flags.append(
                    f"interest coverage {snap.interest_coverage:.1f}x — operating profit "
                    "barely covers the interest bill"
                )

        total += 1
        if snap.operating_cash_flow is not None and snap.net_profit not in (None, 0):
            present += 1
            conversion = snap.operating_cash_flow / snap.net_profit  # type: ignore[operator]
            leverage.append(self._band(conversion, 0.4, 1.0))
            if conversion < 0.5:
                red_flags.append(
                    f"cash conversion {conversion:.2f} — reported profit is not turning "
                    "into cash, which is how accounting profits are manufactured"
                )
            elif conversion >= 1.0:
                strengths.append(f"cash conversion {conversion:.2f} — profits are real cash")
        if leverage:
            components["leverage"] = sum(leverage) / len(leverage)

        # --- Growth --------------------------------------------------------
        growth: list[float] = []
        for value, name in (
            (snap.revenue_growth_yoy, "revenue"),
            (snap.profit_growth_yoy, "profit"),
        ):
            total += 1
            if value is None:
                continue
            present += 1
            growth.append(self._band(value, -5.0, 25.0))
            if value >= 20.0:
                strengths.append(f"{name} +{value:.1f}% YoY")
            elif value < 0:
                concerns.append(f"{name} {value:.1f}% YoY — shrinking")
        if growth:
            components["growth"] = sum(growth) / len(growth)

        # Divergence between the top and bottom line is worth naming.
        both_growth_known = (
            snap.revenue_growth_yoy is not None and snap.profit_growth_yoy is not None
        )
        if both_growth_known and snap.profit_growth_yoy > snap.revenue_growth_yoy + 20:  # type: ignore[operator]
            concerns.append(
                "profit is growing far faster than revenue — check whether margin "
                "expansion is operational or one-off"
            )

        # --- Valuation -----------------------------------------------------
        valuation: list[float] = []
        total += 1
        if snap.pe is not None and snap.pe > 0:
            present += 1
            valuation.append(self._band(snap.pe, 45.0, 12.0, invert=True))
            if snap.industry_pe:
                relative = snap.pe / snap.industry_pe
                if relative < 0.7:
                    strengths.append(
                        f"PE {snap.pe:.1f} vs industry {snap.industry_pe:.1f} — "
                        "at a discount to peers"
                    )
                elif relative > 1.5:
                    concerns.append(
                        f"PE {snap.pe:.1f} vs industry {snap.industry_pe:.1f} — "
                        "priced well above peers; the growth had better arrive"
                    )
        elif snap.pe is not None and snap.pe <= 0:
            present += 1
            valuation.append(0.0)
            concerns.append("negative PE — the company is loss-making")

        total += 1
        if snap.pb is not None:
            present += 1
            valuation.append(self._band(snap.pb, 8.0, 1.5, invert=True))
        if valuation:
            components["valuation"] = sum(valuation) / len(valuation)

        # --- Ownership: not scored, but red flags carry a veto --------------
        total += 1
        if snap.promoter_pledge is not None:
            present += 1
            if snap.promoter_pledge > 25.0:
                red_flags.append(
                    f"{snap.promoter_pledge:.0f}% of the promoter stake is pledged — "
                    "a falling price can force the promoter to sell into it"
                )
            elif snap.promoter_pledge > 0:
                concerns.append(f"{snap.promoter_pledge:.0f}% promoter stake pledged")

        total += 1
        if snap.promoter_holding is not None:
            present += 1
            if snap.promoter_holding < 30.0:
                concerns.append(
                    f"promoter holding {snap.promoter_holding:.1f}% — low skin in the game"
                )
            elif snap.promoter_holding >= 50.0:
                strengths.append(f"promoter holding {snap.promoter_holding:.1f}%")

        total += 1
        if snap.promoter_holding_change is not None:
            present += 1
            if snap.promoter_holding_change <= -2.0:
                red_flags.append(
                    f"promoters cut their stake by {abs(snap.promoter_holding_change):.1f}pp "
                    "this quarter — the people with the most information are selling"
                )
            elif snap.promoter_holding_change >= 1.0:
                strengths.append(
                    f"promoters added {snap.promoter_holding_change:.1f}pp to their stake"
                )

        total += 1
        if snap.fii_holding is not None:
            present += 1

        composite = self._composite(components)
        coverage = present / total if total else 0.0

        return FundamentalScore(
            symbol=snap.symbol,
            composite=round(composite, 4),
            coverage=round(coverage, 4),
            components={k: round(v, 4) for k, v in components.items()},
            strengths=strengths,
            concerns=concerns,
            red_flags=red_flags,
        )

    # --- internals ---------------------------------------------------------
    def _band(self, value: float, poor: float, good: float, invert: bool = False) -> float:
        """Map a raw metric onto 0..1, clamped, linear between the two anchors."""
        if invert:
            # `poor` is the high end (e.g. D/E of 2.0 is bad, 0.3 is good).
            if value <= good:
                return 1.0
            if value >= poor:
                return 0.0
            return (poor - value) / (poor - good)

        if value >= good:
            return 1.0
        if value <= poor:
            return 0.0
        return (value - poor) / (good - poor)

    def _composite(self, components: dict[str, float]) -> float:
        """Renormalise over the components we actually have, so a missing growth
        figure does not silently score as zero growth."""
        available = {k: v for k, v in components.items() if k in WEIGHTS}
        if not available:
            return 0.5  # no information is not bad news; it is no news
        total_weight = sum(WEIGHTS[k] for k in available)
        return sum(WEIGHTS[k] * v for k, v in available.items()) / total_weight
