from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import decrypt, encrypt
from app.db.base_class import Base, TimestampMixin


class BrokerCredential(Base, TimestampMixin):
    """A broker session, encrypted at rest.

    The access token never touches this table in plaintext. ``access_token`` is a
    property that encrypts on write and decrypts on read, so it is impossible to
    persist a raw token by accident — the only way in is through the property.
    """

    __tablename__ = "broker_credentials"
    __table_args__ = (UniqueConstraint("user_id", "broker", name="uq_user_broker"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    broker: Mapped[str] = mapped_column(String(32), default="kite", nullable=False)

    broker_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    encrypted_access_token: Mapped[str] = mapped_column(String(512), nullable=False)
    encrypted_public_token: Mapped[str | None] = mapped_column(String(512), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def access_token(self) -> str:
        return decrypt(self.encrypted_access_token)

    @access_token.setter
    def access_token(self, value: str) -> None:
        self.encrypted_access_token = encrypt(value)

    @property
    def is_expired(self) -> bool:
        expiry = self.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        return datetime.now(UTC) >= expiry

    @property
    def needs_login(self) -> bool:
        return not self.is_active or self.is_expired

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BrokerCredential user={self.user_id} broker={self.broker}>"
