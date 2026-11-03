"""Quota Ledger Repository Port Interface.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

from app.domain.entities.quota import CreditDeductResult, QuotaBalance, QuotaLedger
from app.domain.entities.usage import UsageEvent


@runtime_checkable
class IQuotaRepository(Protocol):
    """Abstract port for quota balances, atomic deductions, and audit logging."""

    def save(self, quota: QuotaLedger) -> None:
        """Initializes or saves a quota ledger record."""
        ...

    def get_by_license_id(self, license_id: str) -> Optional[QuotaLedger]:
        """Retrieves quota ledger associated with a license."""
        ...

    def get_balance(self, license_id: str) -> QuotaBalance:
        """Retrieves current remaining credit balance and usage stats."""
        ...

    def atomic_deduct(
        self,
        license_id: str,
        credits: int,
        idempotency_key: str,
        event_type: str = "api_call",
        metadata: Optional[dict[str, Any]] = None,
    ) -> CreditDeductResult:
        """Atomically deducts credits from balance and logs usage event with ACID guarantees."""
        ...

    def atomic_refund(
        self, license_id: str, idempotency_key: str, window_seconds: int, reason: Optional[str] = None,
        breaker: Optional[Any] = None,
    ) -> CreditDeductResult:
        """Compensates a previous deduct exactly once within ``window_seconds``."""
        ...

    def replenish(
        self, license_id: str, credits: int, reset_cycle: bool = False
    ) -> QuotaLedger:
        """Adds credits to balance and allowance."""
        ...

    def record_usage(self, event: UsageEvent) -> None:
        """Appends discrete usage event to audit trail."""
        ...

    def get_usage_history(self, license_id: str, limit: int = 50) -> list[UsageEvent]:
        """Retrieves chronological audit events for a license."""
        ...

    def get_usage_by_idempotency(self, idempotency_key: str) -> Optional[UsageEvent]:
        """Finds existing usage event by idempotency key for replay checking."""
        ...
