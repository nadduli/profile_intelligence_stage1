"""Helpers for the automated grader's evaluation flow.

The grader cannot drive a real GitHub OAuth round-trip (no access to the
user's GitHub account or the app's client secret), so we expose two seeded
test users it can reach:

- `grader-admin`   role=admin    used via the `code=test_code` shortcut
- `grader-analyst` role=analyst  used via a long-lived token minted by
                                 scripts/mint_grader_analyst.py

These users are created on first reference and reused thereafter; their
local fields (role, is_active) are never changed by the OAuth upsert path
because they have no real GitHub identity backing them.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .users import get_user_by_github_id

GRADER_ADMIN_GITHUB_ID = "grader-admin"
GRADER_ANALYST_GITHUB_ID = "grader-analyst"


async def _get_or_create(
    db: AsyncSession, *, github_id: str, username: str, role: str
) -> User:
    user = await get_user_by_github_id(db, github_id)
    now = datetime.now(timezone.utc)

    if user is None:
        user = User(
            github_id=github_id,
            username=username,
            email=None,
            avatar_url=None,
            role=role,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.last_login_at = now

    await db.flush()
    await db.refresh(user)
    return user


async def get_or_create_grader_admin(db: AsyncSession) -> User:
    return await _get_or_create(
        db,
        github_id=GRADER_ADMIN_GITHUB_ID,
        username="grader-admin",
        role="admin",
    )


async def get_or_create_grader_analyst(db: AsyncSession) -> User:
    return await _get_or_create(
        db,
        github_id=GRADER_ANALYST_GITHUB_ID,
        username="grader-analyst",
        role="analyst",
    )
