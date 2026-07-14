"""Arbitration.

The five agents will disagree. That is the point of having five of them, and an
engine that only fires when all five align would never trade. So the rules for
resolving disagreement have to be written down explicitly, and here they are:

1. **The technical agent proposes.** Nothing else can originate a trade. A
   fundamentally wonderful company is not a reason to buy *today*, and news
   sentiment without a chart setup is chasing headlines.

2. **Fundamentals and news can veto, not propose.** They are filters on a
   technical idea. A red-flagged balance sheet kills a beautiful chart; a
   beautiful balance sheet does not rescue a broken one.

3. **The risk agent has an absolute veto** and is consulted last, because sizing
   depends on the entry and stop that only exist once a trade is proposed.

4. **Contradiction is disqualifying, not averageable.** If the technical agent
   says BUY and the news agent says the company just lost its largest customer,
   the answer is *not* "buy a bit less". Averaging opposing high-conviction views
   produces a position that nobody actually believes in. The answer is: don't
   trade. Conflict is information, and the information is "stay out".

The engine's default is NO_TRADE and everything has to argue its way past that.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.base import Action, Conviction
from app.agents.news_agent import MarketContextAgent
from app.agents.risk_agent import Position, RiskAgent, RiskLimits
from app.agents.technical_agent import TechnicalAgent
from app.core.logging import get_logger
from app.engine.models import Decision, DecisionOutcome, MarketData
from app.indicators import atr

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EngineConfig:
    min_confidence: float = 0.35
    require_conviction: Conviction = Conviction.MODERATE

    atr_length: int = 14
    stop_atr_multiple: float = 2.0
    target_r_multiple: float = 2.0  # target sits at 2R by construction

    # Filters. A negative news score below this kills a long, and vice versa.
    news_veto_threshold: float = 0.4
    fundamental_veto_below: float = 0.30

    allow_shorts: bool = False  # delivery accounts cannot short overnight
    trade_in_ranging_markets: bool = False


class DecisionEngine:
    def __init__(
        self,
        config: EngineConfig | None = None,
        risk_limits: RiskLimits | None = None,
        technical: TechnicalAgent | None = None,
        risk: RiskAgent | None = None,
    ) -> None:
        self.config = config or EngineConfig()
        self.technical = technical or TechnicalAgent()
        self.risk = risk or RiskAgent(risk_limits)
        self.context_agent = MarketContextAgent()

    def decide(
        self,
        data: MarketData,
        equity: float,
        *,
        open_positions: list[Position] | None = None,
        lot_size: int = 1,
    ) -> Decision:
        symbol = data.symbol
        votes: dict[str, str] = {}
        reasons: list[str] = []
        vetoes: list[str] = []

        # --- 1. Technical proposes -----------------------------------------
        view = self.technical.analyze(symbol, data.candles)
        recommendation = view.to_recommendation()
        votes["technical"] = f"{recommendation.action.value} ({view.conviction.value})"

        if recommendation.action is Action.HOLD:
            return self._no_trade(
                symbol,
                view,
                votes,
                [f"technical: {view.summary()}"],
            )

        if view.regime == "ranging" and not self.config.trade_in_ranging_markets:
            return self._no_trade(
                symbol,
                view,
                votes,
                ["market is ranging (low ADX); trend signals are unreliable here"],
            )

        if recommendation.confidence < self.config.min_confidence:
            return self._no_trade(
                symbol,
                view,
                votes,
                [
                    f"technical confidence {recommendation.confidence:.2f} is below "
                    f"the {self.config.min_confidence} floor"
                ],
            )

        if view.conviction is Conviction.LOW:
            return self._no_trade(symbol, view, votes, ["technical conviction is low"])

        action = recommendation.action

        if action is Action.SELL and not self.config.allow_shorts:
            return self._no_trade(
                symbol,
                view,
                votes,
                ["bearish setup, but shorting is disabled on this account"],
            )

        reasons.append(f"technical: {view.summary()}")
        reasons.extend(view.rationale[:3])

        # --- 2. Filters: fundamentals and news may veto ----------------------
        if data.fundamentals is not None:
            f = data.fundamentals
            votes["fundamental"] = f"{f.composite:.2f} (coverage {f.coverage:.0%})"

            if f.red_flags:
                vetoes.append(f"fundamental red flag: {f.red_flags[0]}")
            elif action is Action.BUY and f.composite < self.config.fundamental_veto_below:
                vetoes.append(
                    f"fundamental score {f.composite:.2f} is below the "
                    f"{self.config.fundamental_veto_below} floor for a long"
                )
            else:
                reasons.extend(f"fundamental: {s}" for s in f.strengths[:2])
        else:
            votes["fundamental"] = "no data"

        if data.news is not None:
            n = data.news
            votes["news"] = f"{n.score:+.2f} ({n.item_count} items)"

            # Rule 4: contradiction disqualifies. It is not averaged away.
            contradicts_long = (
                action is Action.BUY and n.score <= -self.config.news_veto_threshold
            )
            contradicts_short = (
                action is Action.SELL and n.score >= self.config.news_veto_threshold
            )
            if contradicts_long or contradicts_short:
                vetoes.append(
                    f"news sentiment ({n.score:+.2f}) directly contradicts the "
                    f"{action.value} setup — conflict is a reason to stay out, "
                    "not to trade smaller"
                )
            elif n.headlines:
                reasons.append(f"news: {n.headlines[0]}")
        else:
            votes["news"] = "no data"

        # --- 3. Market context: advisory, not a veto -------------------------
        if data.context is not None:
            notes = self.context_agent.assess(data.context)
            reasons.extend(f"context: {note}" for note in notes)
            if data.context.risk_off and action is Action.BUY:
                vetoes.append("risk-off backdrop: two or more macro stress signals are firing")

        if vetoes:
            return self._vetoed(symbol, view, votes, reasons, vetoes)

        # --- 4. Risk sizes it, and holds the last veto -----------------------
        entry = float(data.candles["close"].iloc[-1])
        atr_now = float(atr(data.candles, self.config.atr_length).iloc[-1])

        if atr_now <= 0:
            return self._no_trade(symbol, view, votes, ["ATR is zero; cannot place a stop"])

        stop = self.risk.atr_stop(entry, atr_now, action, self.config.stop_atr_multiple)
        risk_per_unit = abs(entry - stop)
        target = (
            entry + self.config.target_r_multiple * risk_per_unit
            if action is Action.BUY
            else entry - self.config.target_r_multiple * risk_per_unit
        )

        assessment = self.risk.assess(
            symbol,
            action,
            entry=entry,
            stop_loss=stop,
            equity=equity,
            target=target,
            lot_size=lot_size,
            open_positions=open_positions,
            returns=data.returns,
        )
        votes["risk"] = "approved" if assessment.approved else "REJECTED"

        if not assessment.approved:
            return Decision(
                symbol=symbol,
                outcome=DecisionOutcome.VETOED,
                action=Action.HOLD,
                confidence=recommendation.confidence,
                technical=view,
                risk=assessment,
                reasons=reasons,
                vetoes=assessment.vetoes,
                agent_votes=votes,
            )

        reasons.extend(f"risk: {note}" for note in assessment.notes)

        decision = Decision(
            symbol=symbol,
            outcome=DecisionOutcome.TRADE,
            action=action,
            confidence=recommendation.confidence,
            quantity=assessment.quantity,
            entry=entry,
            stop_loss=stop,
            target=target,
            technical=view,
            risk=assessment,
            reasons=reasons,
            agent_votes=votes,
        )
        logger.info("Decision: %s", decision.summary())
        return decision

    # --- internals ---------------------------------------------------------
    def _no_trade(self, symbol, view, votes, reasons) -> Decision:  # noqa: ANN001
        return Decision(
            symbol=symbol,
            outcome=DecisionOutcome.NO_TRADE,
            action=Action.HOLD,
            confidence=0.0,
            technical=view,
            reasons=reasons,
            agent_votes=votes,
        )

    def _vetoed(self, symbol, view, votes, reasons, vetoes) -> Decision:  # noqa: ANN001
        decision = Decision(
            symbol=symbol,
            outcome=DecisionOutcome.VETOED,
            action=Action.HOLD,
            confidence=0.0,
            technical=view,
            reasons=reasons,
            vetoes=vetoes,
            agent_votes=votes,
        )
        logger.info("Decision: %s", decision.summary())
        return decision
