"""Pytest fixtures.

The suite runs against an in-memory SQLite database and a fake in-process Redis,
so `pytest` works with zero infrastructure. Integration tests that need real
Postgres are marked with `@pytest.mark.integration` and skipped by default.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.cache import redis_client
from app.core.security import create_access_token
from app.crud.user import user_crud
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.user import User, UserRole
from app.schemas.user import UserCreate

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


class FakeRedis:
    """Minimal stand-in for the handful of Redis calls the app makes."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._store.clear()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(redis_client, "get_redis", lambda: fake)
    return fake


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def trader_user(db_session: AsyncSession) -> User:
    return await user_crud.create(
        db_session,
        UserCreate(
            email="trader@example.com", password="Passw0rd123", full_name="Test Trader"
        ),
    )


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    return await user_crud.create(
        db_session,
        UserCreate(email="admin@example.com", password="Passw0rd123", full_name="Test Admin"),
        role=UserRole.ADMIN,
        is_superuser=True,
        is_verified=True,
    )


def auth_header(user: User) -> dict[str, str]:
    token, _, _ = create_access_token(user.id, {"role": user.role.value})
    return {"Authorization": f"Bearer {token}"}
