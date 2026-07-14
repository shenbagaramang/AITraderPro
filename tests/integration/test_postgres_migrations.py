"""Integration checks that need a real Postgres. Run with: pytest -m integration"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_migrations_have_been_applied() -> None:
    engine = create_async_engine(settings.async_database_uri)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
        )
        tables = {row[0] for row in result}
    await engine.dispose()

    assert {"users", "refresh_tokens", "audit_logs", "alembic_version"} <= tables
