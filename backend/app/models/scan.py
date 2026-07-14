from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base, TimestampMixin


class ScanResult(Base, TimestampMixin):
    """One scanner's verdict on one symbol at one scan.

    Every scan is persisted, including neutrals — the neutral rows are what the
    alert diff compares against, and they are also the raw material the future
    backtester needs ("what did the breakout scanner say on every bar of June").
    """

    __tablename__ = "scan_results"
    __table_args__ = (Index("ix_scan_results_lookup", "user_id", "symbol", "scanner", "id"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    watchlist_id: Mapped[int | None] = mapped_column(
        ForeignKey("watchlists.id", ondelete="SET NULL"), index=True, nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    scanner: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    metrics_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ScannerAlert(Base, TimestampMixin):
    """Raised only when a scanner's state CHANGES into an actionable signal.

    The diff rule is the whole feature. A bollinger squeeze that fired yesterday
    still shows bullish on every rescan; re-alerting on every run would bury the
    one alert that matters under fifty repeats of it, and an alert channel that
    cries wolf gets muted within a week.
    """

    __tablename__ = "scanner_alerts"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    scanner: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
