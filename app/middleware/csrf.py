"""CSRF double-submit-cookie protection.

Applies to cookie-authenticated state-changing requests. Bearer-token
callers (CLI) are exempt — attackers can't set Authorization headers on
victims' browsers, so CSRF doesn't apply.

How it works:
1. On login, the backend sets a csrf_token cookie that JS CAN read.
2. The React app reads it via document.cookie and sends it back as
   X-CSRF-Token header on every POST/PUT/PATCH/DELETE.
3. This middleware compares header against cookie. Mismatch -> 403.

An attacker page can't read our cookies (cross-site), so it can't put
the matching value in a forged header.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)

        # Cookie-auth detector: an access_token cookie means the caller is
        # using session cookies. Bearer-auth callers don't carry it.
        if "access_token" not in request.cookies:
            return await call_next(request)

        cookie_value = request.cookies.get("csrf_token")
        header_value = request.headers.get("X-CSRF-Token")

        if (
            not cookie_value
            or not header_value
            or cookie_value != header_value
        ):
            return JSONResponse(
                status_code=403,
                content={"status": "error", "message": "CSRF validation failed"},
            )

        return await call_next(request)
