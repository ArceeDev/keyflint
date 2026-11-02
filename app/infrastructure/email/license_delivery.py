"""Wiring for license-email delivery outside FastAPI DI (CLI + background retry loop)."""

from __future__ import annotations

import sqlite3

from app.application.services.billing_service import BillingService
from app.application.services.license_service import LicenseService
from app.application.services.quota_service import QuotaService
from app.infrastructure.email.transactional_email_service import TransactionalEmailService
from app.infrastructure.repositories.sqlite_customer_repo import SqliteCustomerRepo
from app.infrastructure.repositories.sqlite_license_repo import SqliteLicenseRepo
from app.infrastructure.repositories.sqlite_quota_repo import SqliteQuotaRepo
from app.infrastructure.repositories.sqlite_webhook_repo import SqliteWebhookRepo


def build_billing_service(conn: sqlite3.Connection) -> BillingService:
    license_repo = SqliteLicenseRepo(conn)
    customer_repo = SqliteCustomerRepo(conn)
    quota_repo = SqliteQuotaRepo(conn)
    return BillingService(
        customer_repo=customer_repo,
        license_repo=license_repo,
        quota_repo=quota_repo,
        webhook_repo=SqliteWebhookRepo(conn),
        license_service=LicenseService(
            license_repo=license_repo,
            customer_repo=customer_repo,
            quota_repo=quota_repo,
            conn=conn,
        ),
        quota_service=QuotaService(quota_repo=quota_repo, license_repo=license_repo),
        email_sender=TransactionalEmailService(),
    )
