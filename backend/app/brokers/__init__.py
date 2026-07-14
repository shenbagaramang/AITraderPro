"""Broker layer.

Everything above this line (agents, engine) talks to the ``Broker`` protocol and
never imports Kite. That is not architectural purity for its own sake — it is what
makes it possible to run the entire decision chain against ``PaperBroker`` with no
account, no API key and no risk, and have it exercise exactly the same code path
that will later place a real order.

Adapters:
    PaperBroker  — in-memory simulation, deterministic, used in tests and dry runs
    KiteBroker   — Zerodha Kite Connect
"""

from app.brokers.base import (
    Broker,
    BrokerError,
    Holding,
    Instrument,
    InsufficientFundsError,
    Margins,
    Order,
    OrderNotFoundError,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Product,
    Quote,
    Validity,
)
from app.brokers.paper import PaperBroker

__all__ = [
    "Broker",
    "BrokerError",
    "Holding",
    "InsufficientFundsError",
    "Instrument",
    "Margins",
    "Order",
    "OrderNotFoundError",
    "OrderRequest",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperBroker",
    "Position",
    "Product",
    "Quote",
    "Validity",
]
