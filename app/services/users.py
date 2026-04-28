import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Fetch a user by primary key. Returns None if not found."""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_github_id(db: AsyncSession, github_id: str) -> User | None:
    """Fetch a user by their GitHub identifier. Returns None if not found."""
    result = await db.execute(select(User).where(User.github_id == github_id))
    return result.scalar_one_or_none()


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
    return user
