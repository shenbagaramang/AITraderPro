"""Create the bootstrap superuser. Idempotent, safe to run on every boot."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.logging import configure_logging  # noqa: E402
from app.db.init_db import init_db  # noqa: E402
from app.db.session import AsyncSessionLocal, dispose_engine  # noqa: E402


async def main() -> None:
    configure_logging()
    async with AsyncSessionLocal() as session:
        await init_db(session)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
