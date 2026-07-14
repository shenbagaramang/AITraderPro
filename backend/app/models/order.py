from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base, TimestampMixin


class OrderStatusDB(str, enum.Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderRecord(Base, TimestampMixin):
    """Our record of an order, independent of the broker's.

    Two things make this table worth having rather than just asking Kite:

    1. ``idempotency_key`` carries a **unique constraint**. This is the database
       enforcing what the code also tries to enforce: a retried request after a
       network timeout cannot become a second live order. This is the single
       highest-value constraint in the schema.
    2. ``rationale`` stores *why* the trade was taken — the agent scores at the
       moment of the decision. Six months later, when reviewing a loser, the
       question is never "what did I buy" but "what was I thinking", and the
       broker cannot answer that.
    """

    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_order_idempotency_key"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    broker: Mapped[str] = mapped_column(String(32), default="paper", nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), default="NSE", nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    product: Mapped[str] = mapped_column(String(8), default="CNC", nullable=False)
    order_type: Mapped[str] = mapped_column(String(8), default="MARKET", nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[OrderStatusDB] = mapped_column(
        Enum(OrderStatusDB, name="order_status", native_enum=False, length=16),
        default=OrderStatusDB.PENDING,
        nullable=False,
        index=True,
    )
    status_message: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_paper: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Why this trade was taken. Serialised agent output at decision time.
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    placed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OrderRecord {self.side} {self.symbol} x{self.quantity} {self.status.value}>"
