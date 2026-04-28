import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import RefreshToken
from .tokens import hash_token


async def store_refresh_token(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        token: str,
        family_id: uuid.UUID,
        expires_at: datetime,
) -> RefreshToken:
    """Hash the raw refresh token and persist its metadata"""
    row = RefreshToken(
        user_id=user_id,
        token_hash=hash_token(token),
        family_id=family_id,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    return row
