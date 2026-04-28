"""Refresh token persistence and rotation.

Hashing on the way in. Rotation with reuse detection on every refresh.
Routes catch the typed exceptions and translate to HTTP responses.
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_extensions import uuid7

from ..config import Settings
from ..models import RefreshToken, User
from .tokens import (
    decode_token,
    encode_access_token,
    encode_refresh_token,
    hash_token,
)
from .users import get_user_by_id


class RefreshTokenError(Exception):
    """Refresh token is invalid, expired, unknown, or reused. Maps to 401."""


class UserDisabledError(Exception):
    """User exists but is_active=False. Maps to 403."""


async def store_refresh_token(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    token: str,
    family_id: uuid.UUID,
    expires_at: datetime,
) -> RefreshToken:
    """Hash the raw refresh token and persist its metadata."""
    row = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(token),
        family_id=family_id,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return row


async def _revoke_family(
    db: AsyncSession, family_id: uuid.UUID, when: datetime
) -> None:
    """Mark all unrevoked tokens in a family as revoked."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id)
        .where(RefreshToken.revoked_at.is_(None))
        .values(revoked_at=when)
    )


async def rotate_refresh_token(
    db: AsyncSession, raw_token: str, settings: Settings
) -> tuple[User, str, str]:
    """Validate, rotate, return (user, new_access_token, new_refresh_token).

    Raises RefreshTokenError on token failure (any kind).
    Raises UserDisabledError if the user is disabled.
    """
    try:
        payload = decode_token(raw_token, "refresh")
    except jwt.ExpiredSignatureError:
        raise RefreshTokenError("Refresh token expired")
    except jwt.InvalidTokenError:
        raise RefreshTokenError("Invalid refresh token")

    try:
        user_id = uuid.UUID(payload["sub"])
        family_id = uuid.UUID(payload["family_id"])
    except (KeyError, ValueError):
        raise RefreshTokenError("Invalid refresh token")

    token_hash_value = hash_token(raw_token)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash_value)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise RefreshTokenError("Refresh token not recognized")

    now = datetime.now(timezone.utc)

    # The critical check: a previously-revoked token presented again means
    # someone has it that shouldn't. Revoke the entire family.
    if row.revoked_at is not None:
        await _revoke_family(db, family_id, now)
        await db.flush()
        raise RefreshTokenError("Refresh token reuse detected")

    if row.expires_at < now:
        raise RefreshTokenError("Refresh token expired")

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise RefreshTokenError("User not found")
    if not user.is_active:
        raise UserDisabledError()

    row.revoked_at = now

    new_access = encode_access_token(user.id, user.role)
    new_refresh = encode_refresh_token(user.id, family_id)
    new_expires_at = now + timedelta(seconds=settings.refresh_token_ttl_seconds)
    await store_refresh_token(
        db,
        user_id=user.id,
        token=new_refresh,
        family_id=family_id,
        expires_at=new_expires_at,
    )

    return user, new_access, new_refresh


async def revoke_by_token(db: AsyncSession, raw_token: str) -> None:
    """Revoke a single refresh token by its raw value. Used on logout.

    No-op if the token is unknown or already revoked.
    """
    token_hash_value = hash_token(raw_token)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash_value)
        .where(RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def issue_session(
    db: AsyncSession,
    user: User,
    settings: Settings,
) -> tuple[str, str]:
    """Issue a fresh (access, refresh) pair for an authenticated user.

    Generates a new family_id (this is a fresh login, not a rotation)
    and persists the hashed refresh token. Returns the raw tokens.
    """
    family_id = uuid7()
    access = encode_access_token(user.id, user.role)
    refresh = encode_refresh_token(user.id, family_id)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.refresh_token_ttl_seconds
    )
    await store_refresh_token(
        db,
        user_id=user.id,
        token=refresh,
        family_id=family_id,
        expires_at=expires_at,
    )
    return access, refresh
