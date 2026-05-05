"""User lookup with a short-TTL in-memory cache.

Every authenticated request goes through `get_current_user`, which
calls `get_user_by_id`. Without a cache, that's one DB round-trip per
request — the dominant cost behind a remote Postgres. The cache amortizes
that to one DB hit per user per TTL window.

TTL is intentionally short (30s) so that admin-driven changes to
is_active or role propagate without manual invalidation. Login
(`upsert_from_github`) does invalidate explicitly so role/status changes
applied just before re-login take effect immediately.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User

_USER_CACHE_TTL_SECONDS = 30
_USER_CACHE_MAX_ENTRIES = 1_000

_user_cache: TTLCache[uuid.UUID, User] = TTLCache(
    maxsize=_USER_CACHE_MAX_ENTRIES, ttl=_USER_CACHE_TTL_SECONDS
)
_user_lock = asyncio.Lock()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Fetch a user by primary key. Cached for `_USER_CACHE_TTL_SECONDS`.

    On cache miss, loads from the DB and detaches the resulting ORM
    instance from the session before caching — the cached User has all
    its scalar attributes loaded but no live session binding, which is
    safe for the read-only access the auth dependency needs.
    """
    async with _user_lock:
        cached = _user_cache.get(user_id)
        if cached is not None:
            return cached

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is not None:
        # Detach so the cached User isn't tied to this request's session.
        # All Profile/User attributes are scalar (no relationships) so a
        # detached instance still serves auth's needs (id, role, is_active).
        db.expunge(user)
        async with _user_lock:
            _user_cache[user_id] = user
    return user


async def get_user_by_github_id(db: AsyncSession, github_id: str) -> User | None:
    """Fetch a user by their GitHub identifier. Returns None if not found."""
    result = await db.execute(select(User).where(User.github_id == github_id))
    return result.scalar_one_or_none()


async def invalidate_user(user_id: uuid.UUID) -> None:
    """Drop a single user from the cache. Used after edits to that user."""
    async with _user_lock:
        _user_cache.pop(user_id, None)


async def invalidate_all_users() -> None:
    """Wipe the user cache. Used by tests for isolation."""
    async with _user_lock:
        _user_cache.clear()


async def upsert_from_github(
    db: AsyncSession,
    *,
    github_id: str,
    username: str,
    email: str | None,
    avatar_url: str | None,
) -> User:
    """Create or update a user from GitHub OAuth data; mark login time.

    Mutable GitHub fields (username, email, avatar) are synced on every
    login. Local fields (role, is_active) are NOT touched on update.
    Invalidates the user cache so any pre-existing cached copy is
    refreshed on the next request.
    """
    user = await get_user_by_github_id(db, github_id)
    now = datetime.now(timezone.utc)

    if user is None:
        user = User(
            github_id=github_id,
            username=username,
            email=email,
            avatar_url=avatar_url,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.username = username
        user.email = email
        user.avatar_url = avatar_url
        user.last_login_at = now

    await db.flush()
    await db.refresh(user)

    # Drop any cached copy so the next get_user_by_id sees the upsert.
    await invalidate_user(user.id)
    return user
