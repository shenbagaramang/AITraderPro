# Phase 1 — Foundation: design notes

Notes on the decisions that are not obvious from reading the code, and the traps that were hit and fixed while building it.

## Why async all the way down

Phase 2 streams live ticks over a WebSocket while serving REST traffic; Phase 4 fans out concurrent scans across hundreds of F&O symbols. Both are IO-bound, so the stack is async end to end: `asyncpg`, `AsyncSession`, `redis.asyncio`, and an async Alembic `env.py`. Retrofitting async onto a sync codebase later is far more painful than paying the cost now.

## Token design

Three properties matter for a system that will eventually place real orders:

1. **Short-lived access tokens** (30 min default) limit the blast radius of a leak.
2. **Refresh rotation** — presenting a refresh token invalidates it and issues a new one. If an attacker steals a refresh token and uses it, the legitimate user's next refresh fails, which is a detectable signal rather than a silent compromise.
3. **Refresh tokens are stored as SHA-256 digests.** A dump of `refresh_tokens` cannot be used to mint sessions.

Logout writes the access token's `jti` into Redis with a TTL equal to its remaining lifetime, so revocation is immediate without a DB lookup on every request. The TTL means the blocklist self-cleans.

## Bugs found and fixed during the build

These were caught by the test suite, not by inspection:

1. **`RequestValidationError` details were not JSON-serialisable.** Pydantic v2 embeds the original `ValueError` object in `ctx`, so `JSONResponse` blew up with a `TypeError` when a weak password was submitted — turning a clean 422 into a 500. Fixed by passing `exc.errors()` through `jsonable_encoder`.
2. **Naive vs aware datetime comparison.** SQLite hands back naive datetimes; comparing `stored.expires_at <= datetime.now(timezone.utc)` raised `TypeError`. Postgres would have masked this. Normalised with an `_as_utc()` helper at the comparison boundary.
3. **`model_copy(update={"role": None})` does not un-set a field** — it *marks it as set*, so `model_dump(exclude_unset=True)` happily wrote `role=None` to a `NOT NULL` column. The self-escalation guard was silently corrupting the row instead of ignoring the field. Fixed by dumping first and popping the keys.

The third one is the reason the guard has its own test rather than being assumed correct.

## Testing without infrastructure

`pytest` runs against in-memory SQLite plus a `FakeRedis` that implements the four methods the app actually calls. `make test` therefore works on a laptop with nothing running. CI additionally runs the `integration` marker against real Postgres, which is where dialect-specific behaviour (like bug #2 above, in reverse) gets caught.

## Extension points for later phases

- `RequireRoles(UserRole.TRADER)` in `core/deps.py` is unused in Phase 1 and exists to gate order endpoints in Phase 2.
- `AuditLog` already has `action`, `resource` and `detail` columns sized for order events.
- `cache/redis_client.py` holds only the blocklist today; quote caching lands beside it.
- `services/` is where the Decision Engine goes. Routers already call services rather than the ORM, so no router changes are needed to introduce it.
