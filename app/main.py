"""KeyForge FastAPI Gateway Application Entrypoint.

File: app/main.py
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.infrastructure.database.migrations import init_db
from app.infrastructure.logging import configure_logging, get_logger
from app.presentation.api.router import api_router
from app.presentation.errors import register_error_handlers
from app.presentation.middlewares import (
    PayloadSizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

logger = get_logger("gateway")
STATIC_DIR = Path(__file__).parent / "presentation" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manages application startup validation, logging, and database schema readiness."""
    settings = get_settings()
    is_prod = settings.ENVIRONMENT.strip().lower() == "production"
    configure_logging(log_level=settings.LOG_LEVEL, use_json=is_prod)
    settings.validate_production_secrets()

    logger.info(f"Starting KeyForge Gateway v{__version__} in '{settings.ENVIRONMENT}' mode...")

    try:
        init_db(settings.DATABASE_PATH)
        logger.info("Database migrations initialized successfully.")
    except Exception as exc:
        logger.error(f"Database migration failure on startup: {exc}")
        raise

    yield

    logger.info("KeyForge Gateway shutdown complete.")


app = FastAPI(
    title="KeyForge",
    description="Cryptographic Licensing & Token-Bucket Quota-Metering Gateway",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 1. Register Exception Handlers (RFC 7807)
register_error_handlers(app)

# 2. Register Middlewares (LIFO: SecurityHeadersMiddleware executes outermost)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(PayloadSizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# 3. Mount Static Assets & Cyber-Minimalist Dashboard
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_dashboard() -> FileResponse:
    """Serves the Cyber-Minimalist Admin UI."""
    index_file = STATIC_DIR / "index.html"
    return FileResponse(index_file)


# 4. Include Unified API Router
app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
