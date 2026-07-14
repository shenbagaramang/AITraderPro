"""Idempotent bootstrap: create the first superuser if it does not exist."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.crud.user import user_crud
from app.models.user import UserRole
from app.schemas.user import UserCreate

logger = get_logger(__name__)


async def init_db(db: AsyncSession) -> None:
    existing = await user_crud.get_by_email(db, settings.FIRST_SUPERUSER_EMAIL)
    if existing:
        logger.info("Superuser already present, skipping bootstrap")
        return

    await user_crud.create(
        db,
        UserCreate(
            email=settings.FIRST_SUPERUSER_EMAIL,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            full_name="Platform Administrator",
        ),
        role=UserRole.ADMIN,
        is_superuser=True,
        is_verified=True,
    )
    logger.info("Created superuser %s", settings.FIRST_SUPERUSER_EMAIL)
