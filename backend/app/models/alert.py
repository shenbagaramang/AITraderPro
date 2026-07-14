from __future__ import annotations

from sqlalchemy import Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base, TimestampMixin


class WebhookAlert(Base, TimestampMixin):
    """Every TradingView alert that arrives, verbatim.

    Alerts are stored before they are judged. When an alert-driven strategy
    misbehaves, the first question is "what exactly did TradingView send and
    when" — and the webhook body is the only evidence.
    """

    __tablename__ = "webhook_alerts"

    source: Mapped[str] = mapped_column(String(32), default="tradingview", nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    alert_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_body: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
