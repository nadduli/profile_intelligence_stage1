"""Mint a long-lived (24h) access token for the grader's analyst test user.

Run this once at submission time and paste the output into the
"Analyst Test Token" field on the submission form.

Usage:
    uv run python scripts/mint_grader_analyst.py

Why a long-lived token: the configured ACCESS_TOKEN_TTL_SECONDS is 180s
(per spec). The grader's test run can outlive that, so we mint a token
with a 24-hour expiry specifically for evaluation. The token is valid
only against the deployed backend that signed it (different JWT_SECRET
on every environment).
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import jwt

# Allow `python scripts/mint_grader_analyst.py` from the repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services.grader import get_or_create_grader_analyst  # noqa: E402

GRADER_TOKEN_TTL_SECONDS = 24 * 3600  # 24 hours


def mint_long_lived_access_token(user_id: uuid.UUID, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=GRADER_TOKEN_TTL_SECONDS)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def main() -> None:
    async with SessionLocal() as db:
        analyst = await get_or_create_grader_analyst(db)
        await db.commit()
        token = mint_long_lived_access_token(analyst.id, analyst.role)
    print(token)


if __name__ == "__main__":
    asyncio.run(main())
