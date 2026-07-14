from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.core.deps import CurrentSuperuser, CurrentUser, DbSession
from app.schemas.common import Message, PaginatedResponse
from app.schemas.user import UserPasswordChange, UserPublic, UserUpdate
from app.services.user_service import user_service

router = APIRouter()


@router.get(
    "",
    response_model=PaginatedResponse[UserPublic],
    summary="List users (admin only)",
)
async def list_users(
    db: DbSession,
    _: CurrentSuperuser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> PaginatedResponse[UserPublic]:
    items, total = await user_service.list_users(db, skip=skip, limit=limit)
    return PaginatedResponse[UserPublic](
        items=[UserPublic.model_validate(u) for u in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.patch("/me", response_model=UserPublic, summary="Update own profile")
async def update_me(payload: UserUpdate, user: CurrentUser, db: DbSession) -> UserPublic:
    # A user may not escalate their own role or flip their own active flag, so those
    # fields are dropped before the update is applied.
    fields = payload.model_dump(exclude_unset=True)
    fields.pop("role", None)
    fields.pop("is_active", None)
    safe = UserUpdate.model_construct(**fields)
    updated = await user_service.update_user(db, user, safe)
    return UserPublic.model_validate(updated)


@router.post("/me/password", response_model=Message, summary="Change own password")
async def change_password(
    payload: UserPasswordChange, user: CurrentUser, db: DbSession
) -> Message:
    await user_service.change_password(db, user, payload)
    return Message(message="Password updated")


@router.get("/{user_id}", response_model=UserPublic, summary="Fetch a user (admin only)")
async def get_user(user_id: int, db: DbSession, _: CurrentSuperuser) -> UserPublic:
    user = await user_service.get_or_404(db, user_id)
    return UserPublic.model_validate(user)


@router.patch("/{user_id}", response_model=UserPublic, summary="Update a user (admin only)")
async def update_user(
    user_id: int, payload: UserUpdate, db: DbSession, _: CurrentSuperuser
) -> UserPublic:
    user = await user_service.get_or_404(db, user_id)
    updated = await user_service.update_user(db, user, payload)
    return UserPublic.model_validate(updated)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=Message,
    summary="Deactivate a user (admin only)",
)
async def deactivate_user(user_id: int, db: DbSession, _: CurrentSuperuser) -> Message:
    user = await user_service.get_or_404(db, user_id)
    await user_service.deactivate(db, user)
    return Message(message=f"User {user_id} deactivated")
