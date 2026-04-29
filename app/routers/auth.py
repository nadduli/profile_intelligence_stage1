import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import Settings, get_settings
from ..database import get_db
from ..models import User
from ..schemas import CliCodeExchange, RefreshTokenRequest, UserResponse
from ..security.deps import get_current_user
from ..security.rate_limit import ip_key, limiter
from ..services.github_oauth import GitHubOAuthError, exchange_code, fetch_user
from ..services.refresh_tokens import (
    RefreshTokenError,
    UserDisabledError,
    issue_session,
    revoke_by_token,
    rotate_refresh_token,
)
from ..services.users import upsert_from_github

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"


def _set_cookie(
    response: Response,
    *,
    name: str,
    value: str,
    max_age: int,
    path: str,
    settings: Settings,
    http_only: bool = True,
) -> None:
    """Set a cookie with the project's standard security flags."""
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        path=path,
        httponly=http_only,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        domain=settings.cookie_domain,
    )


def _set_session_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
    settings: Settings,
) -> None:
    """Attach the three cookies a web session needs."""
    _set_cookie(
        response,
        name="access_token",
        value=access_token,
        max_age=settings.access_token_ttl_seconds,
        path="/",
        settings=settings,
    )
    _set_cookie(
        response,
        name="refresh_token",
        value=refresh_token,
        max_age=settings.refresh_token_ttl_seconds,
        path="/auth",
        settings=settings,
    )
    _set_cookie(
        response,
        name="csrf_token",
        value=csrf_token,
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
        settings=settings,
        http_only=False,
    )


def _redirect_to_login(settings: Settings, error_code: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.web_app_origin}/login?error={error_code}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/github")
@limiter.limit("10/minute", key_func=ip_key)
async def github_login(request: Request, settings: Settings = Depends(get_settings)):
    """Start the web OAuth flow."""
    state = secrets.token_urlsafe(32)
    redirect_uri = f"{settings.backend_public_url}/auth/github/callback"
    params = {
        "client_id": settings.github_web_client_id,
        "redirect_uri": redirect_uri,
        "scope": "read:user user:email",
        "state": state,
    }
    response = RedirectResponse(
        f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}",
        status_code=status.HTTP_302_FOUND,
    )
    _set_cookie(
        response,
        name="oauth_state",
        value=state,
        max_age=600,  # 10 minutes
        path="/auth/github/callback",
        settings=settings,
    )
    return response


@router.get("/github/callback")
@limiter.limit("10/minute", key_func=ip_key)
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Handle GitHub's redirect after the user authorizes (or denies)."""
    if error:
        logger.warning(f"GitHub denied OAuth: {error}")
        return _redirect_to_login(settings, error)

    if not code or not state or not oauth_state or state != oauth_state:
        logger.warning("OAuth state mismatch or missing parameters")
        return _redirect_to_login(settings, "state_mismatch")

    try:
        gh_access_token = await exchange_code(
            code=code,
            client_id=settings.github_web_client_id,
            client_secret=settings.github_web_client_secret,
            redirect_uri=f"{settings.backend_public_url}/auth/github/callback",
        )
        gh_user = await fetch_user(gh_access_token)
    except GitHubOAuthError as e:
        logger.warning(f"GitHub OAuth failed: {e}")
        return _redirect_to_login(settings, "oauth_failed")

    user = await upsert_from_github(
        db,
        github_id=str(gh_user["id"]),
        username=gh_user["login"],
        email=gh_user.get("email"),
        avatar_url=gh_user.get("avatar_url"),
    )

    if not user.is_active:
        return _redirect_to_login(settings, "account_disabled")

    access_token, refresh_token = await issue_session(db, user, settings)
    csrf_token = secrets.token_urlsafe(32)

    response = RedirectResponse(
        f"{settings.web_app_origin}/dashboard",
        status_code=status.HTTP_302_FOUND,
    )
    _set_session_cookies(
        response,
        access_token=access_token,
        refresh_token=refresh_token,
        csrf_token=csrf_token,
        settings=settings,
    )
    response.delete_cookie("oauth_state", path="/auth/github/callback")
    return response

@router.get("/me", response_model=UserResponse)
@limiter.limit("10/minute", key_func=ip_key)
async def me(request: Request, user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return user


@router.post("/refresh")
@limiter.limit("10/minute", key_func=ip_key)
async def refresh(
    request: Request,
    body: RefreshTokenRequest | None = Body(default=None),
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Rotate a refresh token. Accepts cookie (web) or JSON body (CLI)."""
    raw_token = refresh_token or (body.refresh_token if body else None)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No refresh token provided",
        )

    try:
        _user, new_access, new_refresh = await rotate_refresh_token(
            db, raw_token, settings
        )
    except UserDisabledError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )
    except RefreshTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    response = JSONResponse(
        {
            "status": "success",
            "access_token": new_access,
            "refresh_token": new_refresh,
        }
    )

    if refresh_token is not None:
        csrf_token = secrets.token_urlsafe(32)
        _set_session_cookies(
            response,
            access_token=new_access,
            refresh_token=new_refresh,
            csrf_token=csrf_token,
            settings=settings,
        )

    return response

@router.post("/logout")
@limiter.limit("10/minute", key_func=ip_key)
async def logout(
    request: Request,
    body: RefreshTokenRequest | None = Body(default=None),
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Revoke the refresh token and clear session cookies.

    Idempotent. Succeeds whether or not the caller has a valid session.
    """
    raw_token = refresh_token or (body.refresh_token if body else None)
    if raw_token:
        await revoke_by_token(db, raw_token)

    response = JSONResponse({"status": "success"})
    response.delete_cookie("access_token", path="/", domain=settings.cookie_domain)
    response.delete_cookie(
        "refresh_token", path="/auth", domain=settings.cookie_domain
    )
    response.delete_cookie("csrf_token", path="/", domain=settings.cookie_domain)
    return response


@router.post("/cli/exchange")
@limiter.limit("10/minute", key_func=ip_key)
async def cli_exchange(
    request: Request,
    body: CliCodeExchange,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Exchange a GitHub OAuth code (with PKCE verifier) for our session tokens.

    Used by the CLI after capturing the OAuth callback at its loopback server.
    Returns JSON; sets no cookies. CLI persists the tokens locally.
    """
    redirect_uri = f"http://127.0.0.1:{settings.github_cli_callback_port}/callback"

    try:
        gh_access_token = await exchange_code(
            code=body.code,
            client_id=settings.github_cli_client_id,
            client_secret=settings.github_cli_client_secret,
            redirect_uri=redirect_uri,
            code_verifier=body.code_verifier,
        )
        gh_user = await fetch_user(gh_access_token)
    except GitHubOAuthError as e:
        logger.warning(f"CLI OAuth exchange failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="GitHub authentication failed",
        )

    user = await upsert_from_github(
        db,
        github_id=str(gh_user["id"]),
        username=gh_user["login"],
        email=gh_user.get("email"),
        avatar_url=gh_user.get("avatar_url"),
    )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    access_token, refresh_token = await issue_session(db, user, settings)

    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "user": {
            "id": str(user.id),
            "username": user.username,
            "role": user.role,
        },
    }
