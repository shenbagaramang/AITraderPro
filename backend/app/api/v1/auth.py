from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import CurrentUser, DbSession, TokenPayloadDep, client_ip
from app.schemas.common import Message
from app.schemas.token import RefreshRequest, TokenPair
from app.schemas.user import LoginRequest, UserCreate, UserPublic
from app.services.auth_service import auth_service

router = APIRouter()


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new account",
)
async def register(payload: UserCreate, db: DbSession) -> UserPublic:
    user = await auth_service.register(db, payload)
    return UserPublic.model_validate(user)


@router.post(
    "/login", response_model=TokenPair, summary="Exchange credentials for a token pair"
)
async def login(payload: LoginRequest, db: DbSession, request: Request) -> TokenPair:
    return await auth_service.login(
        db,
        payload.email,
        payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )


@router.post(
    "/token",
    response_model=TokenPair,
    summary="OAuth2 password flow, enables the Swagger Authorize button",
)
async def login_oauth2(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    request: Request,
) -> TokenPair:
    return await auth_service.login(
        db,
        form.username,
        form.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )


@router.post("/refresh", response_model=TokenPair, summary="Rotate a refresh token")
async def refresh(payload: RefreshRequest, db: DbSession, request: Request) -> TokenPair:
    return await auth_service.refresh(
        db,
        payload.refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip_address=client_ip(request),
    )


@router.post("/logout", response_model=Message, summary="Revoke all active tokens")
async def logout(user: CurrentUser, payload: TokenPayloadDep, db: DbSession) -> Message:
    await auth_service.logout(db, user, payload["jti"], int(payload["exp"]))
    return Message(message="Logged out")


@router.get("/me", response_model=UserPublic, summary="Current authenticated user")
async def me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)
