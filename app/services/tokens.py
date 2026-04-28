"""JWT and hashing helpers for the auth flow.

Pure functions — no DB access. DB-aware operations (rotation, revocation)
live in the auth router where they're orchestrated.
"""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt

from ..config import get_settings

settings = get_settings()


class InvalidTokenTypeError(jwt.InvalidTokenError):
    """Raised when a token's `type` claim does not match the expected type."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def encode_access_token(user_id: uuid.UUID, role: str) -> str:
    """Issue a short-lived access JWT carrying the user's role."""
    now = _now()
    expires_at = now + timedelta(seconds=settings.access_token_ttl_seconds)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def encode_refresh_token(user_id: uuid.UUID, family_id: uuid.UUID) -> str:
    """Issue a refresh JWT bound to a rotation family."""
    now = _now()
    expires_at = now + timedelta(seconds=settings.refresh_token_ttl_seconds)
    payload = {
        "sub": str(user_id),
        "family_id": str(family_id),
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: Literal["access", "refresh"]) -> dict:
    """Decode and validate a JWT; verify `type` matches `expected_type`.

    Raises:
        jwt.ExpiredSignatureError: token is past its `exp`.
        jwt.InvalidSignatureError: signature does not match.
        jwt.InvalidTokenError: token is malformed.
        InvalidTokenTypeError: signature OK but `type` claim is wrong.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != expected_type:
        raise InvalidTokenTypeError(
            f"expected token type {expected_type!r}, got {payload.get('type')!r}"
        )
    return payload


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Used to store refresh tokens without keeping plaintext."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
