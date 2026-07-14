"""Async Redis client, used for the JWT blocklist and (later) quote caching."""

from __future__ import annotations

from collections.abc import AsyncIterator

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
        logger.info("Redis connection closed")


async def redis_dependency() -> AsyncIterator[Redis]:
    yield get_redis()


# --- JWT blocklist ---------------------------------------------------------
async def blocklist_add(jti: str, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    await get_redis().setex(f"{settings.REDIS_TOKEN_BLOCKLIST_PREFIX}{jti}", ttl_seconds, "1")


async def is_blocklisted(jti: str) -> bool:
    return bool(await get_redis().exists(f"{settings.REDIS_TOKEN_BLOCKLIST_PREFIX}{jti}"))


async def ping() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception as exc:  # pragma: no cover - depends on infra
        logger.warning("Redis ping failed: %s", exc)
        return False
