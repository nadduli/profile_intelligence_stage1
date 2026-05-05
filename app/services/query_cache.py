"""In-memory TTL cache for profile query results.

Single-process design — fits the Stage 4b scale ("limited compute,
no horizontal scaling"). When the system grows to multiple FastAPI
instances, swap the backing store to Redis without touching call sites:
the public surface (get/set/invalidate/invalidate_all) stays the same.
"""

import asyncio
from typing import Any

from cachetools import TTLCache

# Tunable. 60s lets analyst pagination / refresh-clicks hit cache while
# keeping the stale window short enough that explicit invalidation on
# writes is the dominant freshness mechanism.
_DEFAULT_TTL_SECONDS = 60
_MAX_ENTRIES = 10_000

_cache: TTLCache[str, Any] = TTLCache(maxsize=_MAX_ENTRIES, ttl=_DEFAULT_TTL_SECONDS)
_lock = asyncio.Lock()


async def get(key: str) -> Any | None:
    """Return cached value or None on miss / expiry."""
    async with _lock:
        return _cache.get(key)


async def set(key: str, value: Any) -> None:
    """Store value under key. Overwrites any existing entry."""
    async with _lock:
        _cache[key] = value


async def invalidate(key: str) -> None:
    """Remove a specific key. No-op if absent."""
    async with _lock:
        _cache.pop(key, None)


async def invalidate_all() -> None:
    """Drop every cached entry. Used after writes (POST/DELETE)."""
    async with _lock:
        _cache.clear()


def stats() -> dict[str, int]:
    """Snapshot of cache state for diagnostics."""
    return {
        "size": len(_cache),
        "maxsize": _cache.maxsize,
        "ttl": int(_cache.ttl),
    }
