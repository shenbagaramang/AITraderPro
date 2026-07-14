from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.cache import redis_client
from app.core.config import settings
from app.core.deps import DbSession
from app.schemas.common import HealthResponse

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe plus dependency check",
)
async def health(db: DbSession) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    redis_ok = await redis_client.ping()

    return HealthResponse(
        status="ok" if (db_ok and redis_ok) else "degraded",
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        database=db_ok,
        redis=redis_ok,
    )
