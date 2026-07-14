from __future__ import annotations

import json

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base, TimestampMixin

MAX_SYMBOLS = 100


class Watchlist(Base, TimestampMixin):
    """A named basket of symbols to scan.

    Symbols are stored as a JSON array in a text column rather than a join
    table: watchlists are small (capped at 100), always read whole, and never
    queried by member — a join table would buy nothing but migrations.
    """

    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    symbols_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)

    @property
    def symbols(self) -> list[str]:
        return json.loads(self.symbols_json)

    @symbols.setter
    def symbols(self, value: list[str]) -> None:
        cleaned = sorted({s.strip().upper() for s in value if s.strip()})
        if len(cleaned) > MAX_SYMBOLS:
            raise ValueError(f"a watchlist is capped at {MAX_SYMBOLS} symbols")
        self.symbols_json = json.dumps(cleaned)
