"""Reusable FastAPI dependencies: DB session, current user, role guards."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import is_blocklisted
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_token
from app.crud.user import user_crud
from app.db.session import get_db
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_token_payload(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> dict:
    if credentials is None:
        raise AuthenticationError("Missing bearer token", code="token_missing")

    payload = decode_token(credentials.credentials, expected_type="access")
    if await is_blocklisted(payload["jti"]):
        raise AuthenticationError("Token has been revoked", code="token_revoked")
    return payload


TokenPayloadDep = Annotated[dict, Depends(get_token_payload)]


async def get_current_user(db: DbSession, payload: TokenPayloadDep) -> User:
    user = await user_crud.get(db, int(payload["sub"]))
    if user is None:
        raise AuthenticationError("User not found", code="user_missing")
    if not user.is_active:
        raise AuthenticationError("User account is disabled", code="user_inactive")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_superuser(user: CurrentUser) -> User:
    if not user.is_superuser:
        raise PermissionDeniedError()
    return user


CurrentSuperuser = Annotated[User, Depends(get_current_superuser)]


class RequireRoles:
    """Usage: ``Depends(RequireRoles(UserRole.ADMIN, UserRole.TRADER))``.

    Superusers bypass the check. Used from Phase 2 onward to gate order-placing
    endpoints to traders only.
    """

    def __init__(self, *roles: UserRole) -> None:
        self.roles = set(roles)

    async def __call__(self, user: CurrentUser) -> User:
        if user.is_superuser:
            return user
        if user.role not in self.roles:
            allowed = ", ".join(role.value for role in self.roles)
            raise PermissionDeniedError("Requires one of: " + allowed)
        return user


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
