"""KeyForge Quota Application Service.

File: app/application/services/quota_service.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.application.dtos.quota_dtos import (
    QuotaBalanceRequest,
    QuotaBalanceResponse,
    QuotaDeductRequest,
    QuotaDeductResponse,
    QuotaReplenishRequest,
    QuotaReplenishResponse,
)
from app.domain.entities.license import LicenseStatus
from app.domain.exceptions import (
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseRevokedError,
    LicenseSuspendedError,
)
from app.domain.interfaces.license_repository import ILicenseRepository
from app.domain.interfaces.quota_repository import IQuotaRepository


class QuotaService:
    """Orchestrates token-bucket quota metering, atomic deductions, and replenishments."""

    def __init__(
        self,
        quota_repo: IQuotaRepository,
        license_repo: ILicenseRepository,
    ) -> None:
        self._quota_repo = quota_repo
        self._license_repo = license_repo

    def deduct(self, request: QuotaDeductRequest) -> QuotaDeductResponse:
        """Atomically decrements usage credits with paywall protection and idempotency caching."""
        if request.credits <= 0:
            raise ValueError("Credits to deduct must be a positive integer.")

        license_entity = self._license_repo.get_by_key(request.license_key)
        if license_entity is None:
            raise LicenseNotFoundError("License key not found.")

        if license_entity.status == LicenseStatus.REVOKED:
            raise LicenseRevokedError("Cannot consume quota for a revoked license.")
        if license_entity.status == LicenseStatus.SUSPENDED:
            raise LicenseSuspendedError("Cannot consume quota for a suspended license.")

        now = datetime.now(timezone.utc)
        if license_entity.status == LicenseStatus.EXPIRED or license_entity.is_expired(now):
            if license_entity.status != LicenseStatus.EXPIRED:
                self._license_repo.update_status(license_entity.id, LicenseStatus.EXPIRED)
            raise LicenseExpiredError("Cannot consume quota for an expired license.")

        result = self._quota_repo.atomic_deduct(
            license_id=license_entity.id,
            credits=request.credits,
            idempotency_key=request.idempotency_key,
            event_type=request.event_type,
            metadata=request.metadata,
        )

        return QuotaDeductResponse(
            success=result.success,
            license_id=license_entity.id,
            remaining_balance=result.remaining_balance,
            consumed_credits=result.consumed_credits,
            consumed_total=result.consumed_total,
            deducted=request.credits if result.success else 0,
            is_cached=result.is_cached,
            event_id=result.event_id,
            transaction_id=result.event_id,
            idempotency_key=request.idempotency_key,
            license_status=license_entity.status.value,
        )

    def replenish(self, request: QuotaReplenishRequest) -> QuotaReplenishResponse:
        """Replenishes credits upon payment invoice success or quota add-on purchase."""
        if request.credits <= 0:
            raise ValueError("Replenish credits must be a positive integer.")

        license_entity = self._license_repo.get_by_key(request.license_key)
        if license_entity is None:
            raise LicenseNotFoundError("License key not found.")
        if license_entity.status == LicenseStatus.REVOKED:
            raise LicenseRevokedError("Cannot replenish quota for a revoked license.")

        updated_ledger = self._quota_repo.replenish(
            license_id=license_entity.id,
            credits=request.credits,
            reset_cycle=request.reset_cycle,
        )

        return QuotaReplenishResponse(
            success=True,
            license_id=license_entity.id,
            balance=updated_ledger.balance,
            total_allowance=updated_ledger.total_allowance,
            consumed=updated_ledger.consumed,
        )

    def get_balance(self, request: QuotaBalanceRequest) -> QuotaBalanceResponse:
        """Returns real-time credit balance and consumption statistics."""
        license_entity = self._license_repo.get_by_key(request.license_key)
        if license_entity is None:
            raise LicenseNotFoundError("License key not found.")

        balance_info = self._quota_repo.get_balance(license_entity.id)
        return QuotaBalanceResponse(
            license_id=license_entity.id,
            balance=balance_info.balance,
            credit_balance=balance_info.balance,
            total_allowance=balance_info.total_allowance,
            consumed=balance_info.consumed,
            last_reset_at=balance_info.last_reset_at,
        )
