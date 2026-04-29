"""Rate limiter setup and key functions.

Two key functions:
- ip_key: keys by client IP. Used for /auth/* (no user yet at login).
- user_id_or_ip: keys by authenticated user; falls back to IP. Used for /api/*.

Lightweight JWT decode in user_id_or_ip avoids a DB hit on every request.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..services.tokens import decode_token


def ip_key(request: Request) -> str:
    """Per-IP key for unauthenticated rate buckets (auth endpoints)."""
    return f"ip:{get_remote_address(request)}"


def user_id_or_ip(request: Request) -> str:
    """Per-user key when authenticated, else per-IP.

    Reads the access token from the Authorization header (Bearer) or the
    access_token cookie. Decodes only — no DB lookup.
    """
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:]
    else:
        token = request.cookies.get("access_token")

    if token:
        try:
            payload = decode_token(token, "access")
            return f"user:{payload['sub']}"
        except Exception:
            pass

    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=user_id_or_ip)
