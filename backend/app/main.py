"""
app/main.py

FastAPI application entrypoint.
Registers: middleware, exception handlers, routers, startup/shutdown events.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import structlog
import asyncio

from app.config import settings
from app.logging_config import configure_logging
from app.api.schemas import ErrorDetail
from app.db import startup_db, shutdown_db

configure_logging()
log = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    log.info("startup", env=settings.ENV)
    await startup_db(app)
    
    db = app.state.mongo[settings.MONGODB_DB]
    
    # Create indexes
    from pymongo import ASCENDING, TEXT
    await db["chess_games"].create_index([("opening_name", TEXT), ("white", TEXT), ("black", TEXT)])
    await db["lichess_cache"].create_index([("fetched_at", ASCENDING)], expireAfterSeconds=604800)
    await db["review_jobs"].create_index([("status", ASCENDING)])
    
    yield
    # Shutdown
    await shutdown_db(app)
    log.info("shutdown")


app = FastAPI(
    title="PGNSeek",
    description="Search millions of chess games with natural language queries",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Middleware ────────────────────────────────────────────────────────────────

app.state.limiter = limiter


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=ErrorDetail(
            error="rate_limit_exceeded",
            message=f"Too many requests. Limit: {exc.detail}",
            detail={"retry_after": "60s"},
        ).model_dump(),
    )


app.add_exception_handler(RateLimitExceeded, rate_limit_handler)  # type: ignore[arg-type]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Exception handlers ────────────────────────────────────────────────────────


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.error(
        "unhandled_exception", error=str(exc), path=request.url.path, exc_info=exc
    )
    return JSONResponse(
        status_code=500,
        content=ErrorDetail(
            error="internal_server_error",
            message="An unexpected error occurred.",
            detail={"path": str(request.url.path)},
        ).model_dump(),
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Liveness check — also verifies DB connection."""
    try:
        await app.state.mongo.admin.command('ping')
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {
        "status": "ok",
        "db_status": db_status,
    }


# Search router registered here — implemented in api/search.py
from app.api.search import router as search_router

app.include_router(search_router, prefix="/api/v1")

# Review router — implemented in api/review.py
from app.api.review import router as review_router

app.include_router(review_router, prefix="/api/v1")
