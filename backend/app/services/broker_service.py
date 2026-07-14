"""Broker session management: login, vault, and handing out a live Broker."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers.base import Broker, BrokerAuthError
from app.brokers.kite.auth import KiteAuth
from app.brokers.kite.client import KiteBroker
from app.brokers.paper import PaperBroker
from app.core.config import settings
from app.core.exceptions import AppError, NotFoundError
from app.core.logging import get_logger
from app.models.audit_log import AuditLog
from app.models.broker_credential import BrokerCredential
from app.models.user import User

logger = get_logger(__name__)

# Paper brokers are per-user and live for the process lifetime. Real money never
# touches this dict.
_paper_brokers: dict[int, PaperBroker] = {}


class BrokerNotConnectedError(AppError):
    status_code = 428  # Precondition Required
    code = "broker_not_connected"
    message = "No live broker session. Log in to Kite to continue."


class BrokerService:
    def login_url(self) -> str:
        return KiteAuth(settings.KITE_API_KEY, settings.KITE_API_SECRET).login_url()

    async def complete_login(
        self, db: AsyncSession, user: User, request_token: str
    ) -> BrokerCredential:
        """Exchange the one-shot request_token and vault the result."""
        auth = KiteAuth(settings.KITE_API_KEY, settings.KITE_API_SECRET)
        session = auth.exchange(request_token)

        credential = await self._get(db, user.id, "kite")
        if credential is None:
            credential = BrokerCredential(user_id=user.id, broker="kite")
            db.add(credential)

        credential.access_token = session.access_token  # encrypts on assignment
        credential.broker_user_id = session.user_id
        credential.expires_at = session.expires_at
        credential.is_active = True

        db.add(
            AuditLog(
                user_id=user.id,
                action="broker.login",
                resource="kite",
                detail=f"kite user {session.user_id}",
            )
        )
        await db.commit()
        await db.refresh(credential)

        logger.info("Kite session vaulted for user %s", user.id)
        return credential

    async def status(self, db: AsyncSession, user: User) -> dict[str, object]:
        credential = await self._get(db, user.id, "kite")
        if credential is None:
            return {"connected": False, "needs_login": True, "broker": "kite"}
        return {
            "connected": not credential.needs_login,
            "needs_login": credential.needs_login,
            "broker": "kite",
            "broker_user_id": credential.broker_user_id,
            "expires_at": credential.expires_at,
        }

    async def disconnect(self, db: AsyncSession, user: User) -> None:
        credential = await self._get(db, user.id, "kite")
        if credential is None:
            raise NotFoundError("no Kite session to disconnect")
        credential.is_active = False
        db.add(credential)
        db.add(AuditLog(user_id=user.id, action="broker.disconnect", resource="kite"))
        await db.commit()

    async def get_broker(
        self, db: AsyncSession, user: User, *, paper: bool | None = None
    ) -> Broker:
        """Return the Broker this user should be trading through right now.

        Paper is the default unless live trading is explicitly enabled *and* the
        caller explicitly asks for it. Defaulting to live would mean a
        misconfiguration sends real orders, and that is not a mistake worth
        being able to make.
        """
        use_paper = paper if paper is not None else not settings.LIVE_TRADING_ENABLED

        if use_paper:
            if user.id not in _paper_brokers:
                _paper_brokers[user.id] = PaperBroker(
                    starting_cash=settings.PAPER_STARTING_CASH
                )
            return _paper_brokers[user.id]

        if not settings.LIVE_TRADING_ENABLED:
            raise AppError(
                "live trading is disabled (LIVE_TRADING_ENABLED=false)",
                code="live_trading_disabled",
            )

        credential = await self._get(db, user.id, "kite")
        if credential is None or credential.needs_login:
            raise BrokerNotConnectedError(
                "Kite session has expired — it does that every morning at 6am IST. "
                "Log in again to place live orders."
            )

        try:
            return KiteBroker(settings.KITE_API_KEY, credential.access_token)
        except BrokerAuthError as exc:
            raise BrokerNotConnectedError(str(exc)) from exc

    # --- internals ---------------------------------------------------------
    async def _get(
        self, db: AsyncSession, user_id: int, broker: str
    ) -> BrokerCredential | None:
        stmt = select(BrokerCredential).where(
            BrokerCredential.user_id == user_id, BrokerCredential.broker == broker
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    def reset_paper(self, user_id: int) -> None:
        _paper_brokers.pop(user_id, None)


broker_service = BrokerService()
