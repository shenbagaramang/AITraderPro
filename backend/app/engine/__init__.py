"""Decision engine.

The layer where opinions become an order — or, far more often, don't.

    indicators/   pure math
    scanners/     criteria on math
    agents/       interpretation
    engine/       arbitration + execution   <- you are here
    brokers/      the port to the market

The engine's actual job is mostly to say no. It is the only component that can
turn analysis into an irreversible act, so its default answer is NO_TRADE and
every path to an order has to argue its way past a veto.
"""

from app.engine.decision_engine import DecisionEngine, EngineConfig
from app.engine.models import Decision, DecisionOutcome, MarketData

__all__ = [
    "Decision",
    "DecisionEngine",
    "DecisionOutcome",
    "EngineConfig",
    "MarketData",
]
