"""A tiny TTL cache for adapter fetches.

Fundamentals change quarterly and macro data changes by the minute, but neither
changes per-request — and Yahoo rate-limits aggressively enough that an uncached
scan of 50 symbols gets the process temporarily banned. In-memory is enough:
adapters run inside one API process, and staleness of a few minutes is fine for
data of this cadence.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from threading import Lock
from typing import Any, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl_seconds: float, max_entries: int = 512) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = Lock()

    def get_or_fetch(self, key: str, fetch: Callable[[], T]) -> T:
        now = time.monotonic()
        with self._lock:
            hit = self._store.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]

        value = fetch()  # fetch outside the lock: slow calls must not serialise

        with self._lock:
            if len(self._store) >= self.max_entries:
                oldest = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest]
            self._store[key] = (now, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
