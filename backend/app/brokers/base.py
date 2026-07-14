"""The broker contract. Kite is one implementation of this, not the definition of it."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


class BrokerError(RuntimeError):
    """Base for anything the broker refuses or fails to do."""


class OrderNotFoundError(BrokerError):
    pass


class InsufficientFundsError(BrokerError):
    pass


class BrokerAuthError(BrokerError):
    """The session is dead. For Kite this happens every morning by design."""


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, enum.Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"  # stop-loss limit
    SL_M = "SL-M"  # stop-loss market


class Product(str, enum.Enum):
    CNC = "CNC"  # delivery
    MIS = "MIS"  # intraday
    NRML = "NRML"  # F&O carry-forward


class Validity(str, enum.Enum):
    DAY = "DAY"
    IOC = "IOC"


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    @property
    def is_terminal(self) -> bool:
        return self in {OrderStatus.COMPLETE, OrderStatus.CANCELLED, OrderStatus.REJECTED}


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """What we want done.

    ``idempotency_key`` is the single most important field here. A network
    timeout on order placement is ambiguous — the order may or may not have
    reached the exchange — and the naive response, retrying, is how you end up
    accidentally holding twice the position you sized. The key makes a retry
    safe: the same key never places a second order.
    """

    symbol: str
    exchange: str
    side: OrderSide
    quantity: int
    product: Product = Product.CNC
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    trigger_price: float | None = None
    validity: Validity = Validity.DAY
    tag: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.order_type is OrderType.LIMIT and self.price is None:
            raise ValueError("a LIMIT order needs a price")
        if self.order_type in (OrderType.SL, OrderType.SL_M) and self.trigger_price is None:
            raise ValueError(f"{self.order_type.value} needs a trigger_price")
        if self.order_type is OrderType.SL and self.price is None:
            raise ValueError("an SL order needs both a price and a trigger_price")


@dataclass(frozen=True, slots=True)
class Order:
    """What actually happened."""

    order_id: str
    symbol: str
    exchange: str
    side: OrderSide
    quantity: int
    filled_quantity: int
    status: OrderStatus
    product: Product
    order_type: OrderType
    price: float | None = None
    average_price: float | None = None
    trigger_price: float | None = None
    placed_at: datetime | None = None
    status_message: str | None = None
    tag: str | None = None

    @property
    def is_open(self) -> bool:
        return not self.status.is_terminal

    @property
    def pending_quantity(self) -> int:
        return max(self.quantity - self.filled_quantity, 0)


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    exchange: str
    quantity: int  # negative when short
    average_price: float
    last_price: float
    product: Product = Product.MIS
    pnl: float = 0.0

    @property
    def value(self) -> float:
        return abs(self.quantity) * self.last_price


@dataclass(frozen=True, slots=True)
class Holding:
    symbol: str
    exchange: str
    quantity: int
    average_price: float
    last_price: float
    pnl: float = 0.0

    @property
    def value(self) -> float:
        return self.quantity * self.last_price


@dataclass(frozen=True, slots=True)
class Margins:
    available_cash: float
    used_margin: float
    net: float = 0.0


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    last_price: float
    timestamp: datetime | None = None
    volume: int = 0
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None

    @property
    def change_pct(self) -> float | None:
        if self.close:
            return (self.last_price - self.close) / self.close * 100.0
        return None


@dataclass(frozen=True, slots=True)
class Instrument:
    token: int
    symbol: str
    exchange: str
    name: str = ""
    lot_size: int = 1
    tick_size: float = 0.05
    segment: str = ""
    extras: dict[str, str] = field(default_factory=dict)


class Broker(ABC):
    """Every method here is synchronous by design.

    Broker SDKs are blocking, and wrapping them in a fake `async` that secretly
    blocks the event loop is worse than being honest about it. The service layer
    runs these in a threadpool.
    """

    name: str = "broker"

    @abstractmethod
    def is_authenticated(self) -> bool: ...

    @abstractmethod
    def place_order(self, request: OrderRequest) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> Order: ...

    @abstractmethod
    def modify_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
        trigger_price: float | None = None,
    ) -> Order: ...

    @abstractmethod
    def get_order(self, order_id: str) -> Order: ...

    @abstractmethod
    def orders(self) -> list[Order]: ...

    @abstractmethod
    def positions(self) -> list[Position]: ...

    @abstractmethod
    def holdings(self) -> list[Holding]: ...

    @abstractmethod
    def margins(self) -> Margins: ...

    @abstractmethod
    def quote(self, symbols: list[str]) -> dict[str, Quote]: ...
