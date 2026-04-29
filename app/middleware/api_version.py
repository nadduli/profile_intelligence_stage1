"""Enforce X-API-Version: 1 on /api/* requests."""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

REQUIRED_VERSION = "1"


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Reject /api/* requests that don't carry X-API-Version: 1.

    OPTIONS requests are passed through so CORS preflight is unaffected.
    Non-/api paths (auth, health, etc.) are also unaffected.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        version = request.headers.get("X-API-Version")
        if not version:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": "API version header required",
                },
            )
        if version != REQUIRED_VERSION:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": f"Unsupported API version: {version}",
                },
            )

        return await call_next(request)
