import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .database import Base, engine
from .routers import profiles

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up application")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    logger.info("Shutting down application")
    await engine.dispose()


app = FastAPI(title="Profile Intelligence Service", lifespan=lifespan)


app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.warning(f"HTTP Exception: {exc.status_code} - {exc.detail}")
    if exc.status_code == 502:
        return JSONResponse(
            status_code=502,
            content={"status": "502", "message": exc.detail},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail},
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
