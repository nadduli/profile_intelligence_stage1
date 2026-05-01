"""In-memory sliding-window rate limiter.

A backstop alongside the slowapi decorators — slowapi's IP detection has
proved unreliable behind some proxies, so this middleware re-enforces the
Stage 3 spec limits with explicit X-Forwarded-For parsing:

  /auth/*  : 10 requests / minute / client IP
  /api/*   : 60 requests / minute / authenticated user (or IP if anonymous)

Returns 429 with the project's standard `{status, message}` envelope.
"""

import time
from collections import defaultdict, deque

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..services.tokens import decode_token

WINDOW_SECONDS = 60.0
AUTH_LIMIT = 10
API_LIMIT = 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    # Class-level so tests can reset between cases; in production each
    # process has exactly one middleware instance, so behavior is identical.
    _buckets: dict[str, deque[float]] = defaultdict(deque)

    def __init__(self, app):
        super().__init__(app)

    @classmethod
    def reset(cls) -> None:
        """Clear all rate-limit state. Used by tests."""
        cls._buckets.clear()

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    @staticmethod
    def _user_or_ip(request: Request) -> str:
        # Authorization header first, then access_token cookie.
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
        if not token:
            token = request.cookies.get("access_token")

        if token:
            try:
                payload = decode_token(token, "access")
                sub = payload.get("sub")
                if sub:
                    return f"user:{sub}"
            except (jwt.PyJWTError, Exception):
                pass

        return f"ip:{RateLimitMiddleware._client_ip(request)}"

    def _scope(self, request: Request) -> tuple[str, int] | None:
        path = request.url.path
        if path.startswith("/auth/"):
            return f"auth:{self._client_ip(request)}", AUTH_LIMIT
        if path.startswith("/api/"):
            return f"api:{self._user_or_ip(request)}", API_LIMIT
        return None

    async def dispatch(self, request, call_next):
        scope = self._scope(request)
        if scope is None:
            return await call_next(request)

        key, limit = scope
        now = time.monotonic()
        cutoff = now - WINDOW_SECONDS
        bucket = self._buckets[key]

        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            return JSONResponse(
                status_code=429,
                content={"status": "error", "message": "Rate limit exceeded"},
                headers={"Retry-After": "60"},
            )

        bucket.append(now)
        return await call_next(request)
