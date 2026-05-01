import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import get_settings
from .database import engine
from .middleware.api_version import APIVersionMiddleware
from .middleware.csrf import CSRFMiddleware
from .middleware.rate_limit import RateLimitMiddleware
from .middleware.request_logging import RequestLoggingMiddleware
from .routers import auth, profiles, users
from .security.rate_limit import limiter

settings = get_settings()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up application")
    yield
    logger.info("Shutting down application")
    await engine.dispose()


app = FastAPI(title="Profile Intelligence Service", lifespan=lifespan)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    response = JSONResponse(
        status_code=429,
        content={"status": "error", "message": "Rate limit exceeded"},
    )
    retry_after = getattr(exc, "retry_after", None)
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    # Explicit origin gets credentialed access (cookies). The regex echoes
    # any other http(s) origin's header back so external test runners and
    # API clients still get a usable CORS response — they just can't ride
    # cookies. CSRF middleware still gates state-changing cookie requests.
    allow_origins=[settings.web_app_origin],
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(APIVersionMiddleware)
app.add_middleware(RequestLoggingMiddleware)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Single handler for FastAPI HTTPException AND Starlette routing errors.

    Catches 405 Method Not Allowed (raised by Starlette's router, not by us)
    so it gets the standard `{status, message}` envelope instead of the
    default `{detail}` shape.
    """
    logger.warning(f"HTTP Exception: {exc.status_code} - {exc.detail}")
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation Error: {exc.errors()}")
    errors = exc.errors()
    first = errors[0] if errors else {}
    msg = first.get("msg", "Invalid request data")
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": msg},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"},
    )


app.include_router(profiles.router)
app.include_router(users.router)
app.include_router(auth.router)


@app.get("/")
def root():
    return {"message": "Hello from profile-intelligence-stage1!"}


@app.get("/health")
async def health():
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "degraded", "database": "disconnected"}
