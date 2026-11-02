"""KeyFlint FastAPI Gateway Application Entrypoint.

File: app/main.py
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
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


def _retry_failed_emails_once() -> dict[str, int]:
    from app.infrastructure.database.connection import create_connection
    from app.infrastructure.email.license_delivery import build_billing_service

    conn = create_connection()
    try:
        return build_billing_service(conn).retry_failed_license_emails()
    finally:
        conn.close()


async def _email_retry_loop(interval_seconds: int) -> None:
    """Automatically retries failed license emails so a provider outage never loses a buyer."""
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            summary = await asyncio.to_thread(_retry_failed_emails_once)
            if summary.get("retried"):
                logger.info(f"License email retry pass: {summary}")
        except Exception as exc:  # keep the loop alive
            logger.error(f"License email retry pass failed: {exc}")


async def _backup_check_loop(interval_seconds: int, heartbeat_url: str | None) -> None:
    """Hourly restore-and-compare of the Litestream replica, with an optional dead-man heartbeat."""
    from app.bootstrap import LITESTREAM_CONFIG
    from app.infrastructure.backup_check import verify_once

    db_path = Path(get_settings().DATABASE_PATH)
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await asyncio.to_thread(verify_once, db_path, Path(LITESTREAM_CONFIG), heartbeat_url)
        except Exception as exc:  # keep the loop alive
            logger.error(f"Backup verification pass crashed: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manages application startup validation, logging, and database schema readiness."""
    settings = get_settings()
    is_prod = settings.ENVIRONMENT.strip().lower() == "production"
    configure_logging(log_level=settings.LOG_LEVEL, use_json=is_prod)
    settings.validate_production_secrets()

    logger.info(f"Starting KeyFlint Gateway v{__version__} in '{settings.ENVIRONMENT}' mode...")

    try:
        init_db(settings.DATABASE_PATH)
        logger.info("Database migrations initialized successfully.")
    except Exception as exc:
        logger.error(f"Database migration failure on startup: {exc}")
        raise

    from app.infrastructure.email.transactional_email_service import TransactionalEmailService

    email_provider = TransactionalEmailService().provider
    if email_provider == "none":
        logger.warning(
            "EMAIL PROVIDER NOT CONFIGURED: paid licenses will be issued but NOT emailed. "
            "Set RESEND_API_KEY (or SMTP_HOST) as a secret."
        )
    else:
        logger.info(f"License emails via '{email_provider}'.")

    retry_task: asyncio.Task[None] | None = None
    if settings.EMAIL_RETRY_INTERVAL_SECONDS > 0:
        retry_task = asyncio.create_task(_email_retry_loop(settings.EMAIL_RETRY_INTERVAL_SECONDS))
    backup_task: asyncio.Task[None] | None = None
    if settings.BACKUP_CHECK_INTERVAL_SECONDS > 0:
        backup_task = asyncio.create_task(
            _backup_check_loop(settings.BACKUP_CHECK_INTERVAL_SECONDS, settings.BACKUP_HEARTBEAT_URL)
        )

    yield

    for task in (retry_task, backup_task):
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    logger.info("KeyFlint Gateway shutdown complete.")


app = FastAPI(
    title="KeyFlint",
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
