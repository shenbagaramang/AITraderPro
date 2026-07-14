"""Kite's login flow, and the fact that it expires every single day.

This is the part of Kite that surprises people. The access token is **not** a
long-lived API key: it dies at around 6am IST every morning, and the only way to
mint a new one is a browser redirect that a human has to click through. There is
no headless refresh, by regulatory design.

Practical consequences the rest of the system has to live with:

- Any scheduled job that runs before the human has logged in **will** fail auth,
  and must fail loudly rather than silently skipping the day's trades.
- The token is a bearer credential that can place orders, so it is stored
  Fernet-encrypted (see ``core/crypto.py``), never in plaintext.
- ``needs_login`` is what the dashboard shows a big red banner for.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone

from app.brokers.base import BrokerAuthError
from app.core.logging import get_logger

logger = get_logger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
# Kite invalidates tokens each morning. 06:00 IST is the conservative assumption.
TOKEN_EXPIRY_IST = time(6, 0)


@dataclass(frozen=True, slots=True)
class KiteSession:
    access_token: str
    public_token: str | None
    user_id: str
    issued_at: datetime

    @property
    def expires_at(self) -> datetime:
        """The next 06:00 IST after issuance."""
        issued_ist = self.issued_at.astimezone(IST)
        expiry = issued_ist.replace(
            hour=TOKEN_EXPIRY_IST.hour,
            minute=TOKEN_EXPIRY_IST.minute,
            second=0,
            microsecond=0,
        )
        if issued_ist >= expiry:
            expiry += timedelta(days=1)
        return expiry.astimezone(UTC)

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expires_at


class KiteAuth:
    """Wraps the three-legged login. Import of ``kiteconnect`` is deferred so the
    package is not a hard dependency of the test suite or the dashboard image."""

    def __init__(self, api_key: str, api_secret: str) -> None:
        if not api_key or not api_secret:
            raise BrokerAuthError("KITE_API_KEY and KITE_API_SECRET must both be set")
        self.api_key = api_key
        self.api_secret = api_secret

    def _kite(self):  # noqa: ANN202
        try:
            from kiteconnect import KiteConnect
        except ImportError as exc:  # pragma: no cover
            raise BrokerAuthError(
                "the `kiteconnect` package is not installed; "
                "run `pip install kiteconnect` to use the live broker"
            ) from exc
        return KiteConnect(api_key=self.api_key)

    def login_url(self) -> str:
        """Step 1. Send the human here; Kite redirects back with a request_token."""
        return self._kite().login_url()

    def exchange(self, request_token: str) -> KiteSession:
        """Step 2. Trade the one-shot request_token for today's access_token."""
        try:
            data = self._kite().generate_session(request_token, api_secret=self.api_secret)
        except Exception as exc:  # noqa: BLE001 - kiteconnect raises a wide variety
            raise BrokerAuthError(f"Kite rejected the request token: {exc}") from exc

        logger.info("Kite session established for user %s", data.get("user_id"))
        return KiteSession(
            access_token=data["access_token"],
            public_token=data.get("public_token"),
            user_id=data["user_id"],
            issued_at=datetime.now(UTC),
        )
