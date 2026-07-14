from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.crud.base import CRUDBase
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserUpdate


class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    async def get_by_email(self, db: AsyncSession, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        return (await db.execute(stmt)).scalar_one_or_none()

    async def create(  # type: ignore[override]
        self,
        db: AsyncSession,
        obj_in: UserCreate,
        *,
        role: UserRole = UserRole.TRADER,
        is_superuser: bool = False,
        is_verified: bool = False,
    ) -> User:
        user = User(
            email=obj_in.email.lower(),
            hashed_password=hash_password(obj_in.password),
            full_name=obj_in.full_name,
            role=role,
            is_superuser=is_superuser,
            is_verified=is_verified,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def authenticate(self, db: AsyncSession, email: str, password: str) -> User | None:
        user = await self.get_by_email(db, email)
        if not user or not verify_password(password, user.hashed_password):
            return None
        return user

    async def set_password(self, db: AsyncSession, user: User, new_password: str) -> User:
        user.hashed_password = hash_password(new_password)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def touch_last_login(self, db: AsyncSession, user: User) -> None:
        user.last_login_at = datetime.now(UTC)
        db.add(user)
        await db.commit()


user_crud = CRUDUser(User)
