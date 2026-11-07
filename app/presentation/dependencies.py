"""FastAPI Dependency Injection Providers & Admin Guards."""

from __future__ import annotations

from datetime import datetime, timezone
import hmac
import sqlite3
from typing import Any, Iterator, Optional

from fastapi import Depends, Header, HTTPException, Request

from app.application.dtos.common import ResponseMetadata
from app.application.services.billing_service import BillingService
from app.application.services.depletion_notifier import DepletionNotifier
from app.application.services.license_service import LicenseService
from app.application.services.quota_service import QuotaService
from app.config import get_settings
from app.infrastructure.database.connection import create_connection
from app.infrastructure.email.transactional_email_service import TransactionalEmailService
from app.infrastructure.repositories.sqlite_customer_repo import SqliteCustomerRepo
from app.infrastructure.repositories.sqlite_license_repo import SqliteLicenseRepo
from app.infrastructure.repositories.sqlite_portal_token_repo import SqlitePortalTokenRepo
from app.infrastructure.repositories.sqlite_quota_repo import SqliteQuotaRepo
from app.infrastructure.repositories.sqlite_webhook_repo import SqliteWebhookRepo
from app.presentation.middlewares import get_request_id


def build_response_metadata(request: Request) -> dict[str, Any]:
    """Builds ResponseMetadata synced with the active request's X-Request-ID."""
    return ResponseMetadata(
        request_id=get_request_id(request),
        timestamp=datetime.now(timezone.utc).isoformat(),
    ).model_dump()


def require_admin_access(
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """Enforces X-Admin-Key authentication on privileged administrative routes.

    - In ENVIRONMENT='production': X-Admin-Key is strictly mandatory and compared in constant time.
    - In development/test: unauthenticated local demo calls without X-Admin-Key are permitted,
      while explicitly supplied invalid keys are rejected with 401.
    """
    settings = get_settings()
    expected = (settings.ADMIN_API_KEY or "").strip()
    is_prod = settings.ENVIRONMENT.strip().lower() == "production"

    if is_prod:
        if not x_admin_key or not expected or not hmac.compare_digest(
            x_admin_key.encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(
                status_code=401,
                detail="Valid X-Admin-Key header is required in production.",
            )
        return

    if x_admin_key is not None and expected:
        if not hmac.compare_digest(x_admin_key.encode("utf-8"), expected.encode("utf-8")):
            raise HTTPException(
                status_code=401,
                detail="Invalid X-Admin-Key header.",
            )


def get_db() -> Iterator[sqlite3.Connection]:
    """Yields a managed SQLite connection that closes upon request completion."""
    conn = create_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_customer_repo(conn: sqlite3.Connection = Depends(get_db)) -> SqliteCustomerRepo:
    return SqliteCustomerRepo(conn)


def get_license_repo(conn: sqlite3.Connection = Depends(get_db)) -> SqliteLicenseRepo:
    return SqliteLicenseRepo(conn)


def get_quota_repo(conn: sqlite3.Connection = Depends(get_db)) -> SqliteQuotaRepo:
    return SqliteQuotaRepo(conn)


def get_webhook_repo(conn: sqlite3.Connection = Depends(get_db)) -> SqliteWebhookRepo:
    return SqliteWebhookRepo(conn)


def get_portal_token_repo(conn: sqlite3.Connection = Depends(get_db)) -> SqlitePortalTokenRepo:
    return SqlitePortalTokenRepo(conn)


def get_license_service(
    license_repo: SqliteLicenseRepo = Depends(get_license_repo),
    customer_repo: SqliteCustomerRepo = Depends(get_customer_repo),
    quota_repo: SqliteQuotaRepo = Depends(get_quota_repo),
    conn: sqlite3.Connection = Depends(get_db),
) -> LicenseService:
    return LicenseService(
        license_repo=license_repo,
        customer_repo=customer_repo,
        quota_repo=quota_repo,
        conn=conn,
    )


def get_email_sender() -> TransactionalEmailService:
    """Returns singleton transactional email service adapter."""
    return TransactionalEmailService()


def get_quota_service(
    quota_repo: SqliteQuotaRepo = Depends(get_quota_repo),
    license_repo: SqliteLicenseRepo = Depends(get_license_repo),
    customer_repo: SqliteCustomerRepo = Depends(get_customer_repo),
    conn: sqlite3.Connection = Depends(get_db),
    email_sender: TransactionalEmailService = Depends(get_email_sender),
) -> QuotaService:
    return QuotaService(
        quota_repo=quota_repo,
        license_repo=license_repo,
        depletion_notifier=DepletionNotifier(conn, customer_repo, email_sender),
    )


def get_billing_service(
    customer_repo: SqliteCustomerRepo = Depends(get_customer_repo),
    license_repo: SqliteLicenseRepo = Depends(get_license_repo),
    quota_repo: SqliteQuotaRepo = Depends(get_quota_repo),
    webhook_repo: SqliteWebhookRepo = Depends(get_webhook_repo),
    license_service: LicenseService = Depends(get_license_service),
    quota_service: QuotaService = Depends(get_quota_service),
    email_sender: TransactionalEmailService = Depends(get_email_sender),
    portal_token_repo: SqlitePortalTokenRepo = Depends(get_portal_token_repo),
) -> BillingService:
    return BillingService(
        customer_repo=customer_repo,
        license_repo=license_repo,
        quota_repo=quota_repo,
        webhook_repo=webhook_repo,
        license_service=license_service,
        quota_service=quota_service,
        email_sender=email_sender,
        portal_token_repo=portal_token_repo,
    )
