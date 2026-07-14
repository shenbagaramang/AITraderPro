"""User management use-cases sitting above the CRUD layer."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.security import verify_password
from app.crud.user import user_crud
from app.models.user import User
from app.schemas.user import UserPasswordChange, UserUpdate


class UserService:
    async def get_or_404(self, db: AsyncSession, user_id: int) -> User:
        user = await user_crud.get(db, user_id)
        if not user:
            raise NotFoundError(f"User {user_id} not found")
        return user

    async def list_users(
        self, db: AsyncSession, *, skip: int = 0, limit: int = 50
    ) -> tuple[list[User], int]:
        items = list(await user_crud.list(db, skip=skip, limit=limit))
        total = await user_crud.count(db)
        return items, total

    async def update_user(self, db: AsyncSession, user: User, payload: UserUpdate) -> User:
        email_changed = bool(payload.email) and payload.email.lower() != user.email
        if email_changed and await user_crud.get_by_email(db, payload.email):
            raise ConflictError("That email is already in use")
        data = payload.model_dump(exclude_unset=True)
        if "email" in data and data["email"]:
            data["email"] = data["email"].lower()
        return await user_crud.update(db, user, data)

    async def change_password(
        self, db: AsyncSession, user: User, payload: UserPasswordChange
    ) -> User:
        if not verify_password(payload.current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect")
        return await user_crud.set_password(db, user, payload.new_password)

    async def deactivate(self, db: AsyncSession, user: User) -> User:
        return await user_crud.update(db, user, {"is_active": False})


user_service = UserService()
