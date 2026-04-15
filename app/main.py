from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .routers import profiles
from .database import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="Profile Intelligence Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
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
    errors = exc.errors()
    first = errors[0] if errors else {}
    msg = first.get("msg", "Invalid request data")
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": msg},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"},
    )


app.include_router(profiles.router)


@app.get("/")
def root():
    return {"message": "Hello from profile-intelligence-stage1!"}


@app.get("/health")
def health():
    return {"status": "ok"}