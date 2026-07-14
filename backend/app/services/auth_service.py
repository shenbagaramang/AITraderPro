"""Authentication use-cases: register, login, refresh (with rotation), logout."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import blocklist_add, is_blocklisted
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
)
from app.crud.user import user_crud
from app.models.audit_log import AuditLog
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.token import TokenPair
from app.schemas.user import UserCreate

logger = get_logger(__name__)


def _as_utc(value: datetime) -> datetime:
    """Some drivers (SQLite) hand back naive datetimes; normalise before comparing."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class AuthService:
    async def register(self, db: AsyncSession, payload: UserCreate) -> User:
        if await user_crud.get_by_email(db, payload.email):
            raise ConflictError("A user with that email already exists")
        user = await user_crud.create(db, payload)
        await self._audit(db, user.id, "user.register")
        logger.info("Registered user %s", user.email)
        return user

    async def login(
        self,
        db: AsyncSession,
        email: str,
        password: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        user = await user_crud.authenticate(db, email, password)
        if not user:
            await self._audit(db, None, "user.login_failed", detail=email, ip=ip_address)
            raise AuthenticationError("Incorrect email or password")
        if not user.is_active:
            raise AuthenticationError("User account is disabled", code="user_inactive")

        await user_crud.touch_last_login(db, user)
        await self._audit(db, user.id, "user.login", ip=ip_address)
        return await self._issue_pair(db, user, user_agent=user_agent, ip_address=ip_address)

    async def refresh(
        self,
        db: AsyncSession,
        refresh_token: str,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        payload = decode_token(refresh_token, expected_type="refresh")
        jti = payload["jti"]

        if await is_blocklisted(jti):
            raise AuthenticationError("Refresh token has been revoked", code="token_revoked")

        stmt = select(RefreshToken).where(RefreshToken.jti == jti)
        stored = (await db.execute(stmt)).scalar_one_or_none()
        if not stored or stored.revoked or stored.token_hash != hash_token(refresh_token):
            raise AuthenticationError("Refresh token is not recognised", code="token_revoked")
        if _as_utc(stored.expires_at) <= datetime.now(UTC):
            raise AuthenticationError("Refresh token has expired", code="token_expired")

        user = await user_crud.get(db, int(payload["sub"]))
        if not user or not user.is_active:
            raise AuthenticationError("User no longer active", code="user_inactive")

        # Rotation: the presented token dies the moment a new one is issued.
        await self._revoke(db, stored)
        return await self._issue_pair(db, user, user_agent=user_agent, ip_address=ip_address)

    async def logout(
        self, db: AsyncSession, user: User, access_jti: str, access_exp: int
    ) -> None:
        ttl = max(access_exp - int(datetime.now(UTC).timestamp()), 0)
        await blocklist_add(access_jti, ttl)

        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False))
            .values(revoked=True)
        )
        await db.execute(stmt)
        await db.commit()
        await self._audit(db, user.id, "user.logout")
        logger.info("Logged out user %s", user.email)

    # --- internals ---------------------------------------------------------
    async def _issue_pair(
        self,
        db: AsyncSession,
        user: User,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> TokenPair:
        access, _, access_exp = create_access_token(
            user.id, {"role": user.role.value, "email": user.email}
        )
        refresh, refresh_jti, refresh_exp = create_refresh_token(user.id)

        db.add(
            RefreshToken(
                user_id=user.id,
                jti=refresh_jti,
                token_hash=hash_token(refresh),
                expires_at=refresh_exp,
                user_agent=(user_agent or "")[:255] or None,
                ip_address=ip_address,
            )
        )
        await db.commit()

        return TokenPair(access_token=access, refresh_token=refresh, expires_at=access_exp)

    async def _revoke(self, db: AsyncSession, token: RefreshToken) -> None:
        token.revoked = True
        db.add(token)
        await db.commit()
        ttl = int((_as_utc(token.expires_at) - datetime.now(UTC)).total_seconds())
        await blocklist_add(token.jti, ttl)

    async def _audit(
        self,
        db: AsyncSession,
        user_id: int | None,
        action: str,
        *,
        detail: str | None = None,
        ip: str | None = None,
    ) -> None:
        from app.core.logging import request_id_ctx

        db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                resource="auth",
                detail=detail,
                ip_address=ip,
                request_id=request_id_ctx.get(),
            )
        )
        await db.commit()


auth_service = AuthService()
