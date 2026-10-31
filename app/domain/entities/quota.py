"""Quota Ledger and Credit Deduction Domain Entities & Value Objects.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.domain.exceptions import QuotaExceededError


@dataclass(frozen=True)
class CreditDeductResult:
    """Immutable value object detailing the outcome of a quota deduction."""

    success: bool
    remaining_balance: int
    consumed_credits: int
    cumulative_consumed: int = 0
    is_cached: bool = False
    event_id: Optional[str] = None
    reason: Optional[str] = None

    def __init__(
        self,
        success: bool = True,
        remaining_balance: Optional[int] = None,
        consumed_credits: Optional[int] = None,
        is_cached: bool = False,
        event_id: Optional[str] = None,
        reason: Optional[str] = None,
        *,
        credits_deducted: Optional[int] = None,
        balance_remaining: Optional[int] = None,
        consumed_total: Optional[int] = None,
    ) -> None:
        rem_bal = balance_remaining if balance_remaining is not None else (remaining_balance if remaining_balance is not None else 0)
        cons = credits_deducted if credits_deducted is not None else (consumed_credits if consumed_credits is not None else 0)
        cum_cons = consumed_total if consumed_total is not None else cons
        cached = is_cached or (reason == "idempotent_replay")
        object.__setattr__(self, "success", success)
        object.__setattr__(self, "remaining_balance", rem_bal)
        object.__setattr__(self, "consumed_credits", cons)
        object.__setattr__(self, "cumulative_consumed", cum_cons)
        object.__setattr__(self, "is_cached", cached)
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "reason", reason)

    @property
    def credits_deducted(self) -> int:
        """Alias for consumed_credits."""
        return self.consumed_credits

    @property
    def balance_remaining(self) -> int:
        """Alias for remaining_balance."""
        return self.remaining_balance

    @property
    def consumed_total(self) -> int:
        """Returns cumulative cycle consumption across the quota ledger."""
        return self.cumulative_consumed


# Alias for compatibility with domain contracts
DeductResult = CreditDeductResult


@dataclass(frozen=True, slots=True)
class QuotaBalance:
    """Snapshot value object of a license quota balance."""

    license_id: str
    balance: int
    total_allowance: int
    consumed: int
    last_reset_at: datetime


@dataclass(slots=True)
class QuotaLedger:
    """Tracks token-bucket quota allowance, remaining balance, and usage totals."""

    id: str
    license_id: str
    total_allowance: int = 1000
    balance: int = 1000
    consumed: int = 0
    last_reset_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def can_deduct(self, credits: int) -> bool:
        """Determines if sufficient quota credits remain."""
        return credits > 0 and self.balance >= credits

    def deduct(self, credits: int) -> CreditDeductResult:
        """Consumes credits and updates balances or raises QuotaExceededError."""
        if credits <= 0:
            raise ValueError(f"Deduction credits must be positive integer, got {credits}")
        if self.balance < credits:
            raise QuotaExceededError(
                f"Token quota exhausted. Remaining balance: {self.balance} credits.",
                details={
                    "license_id": self.license_id,
                    "remaining_credits": self.balance,
                    "requested_credits": credits,
                },
            )
        self.balance -= credits
        self.consumed += credits
        self.updated_at = datetime.now(timezone.utc)
        return CreditDeductResult(
            success=True,
            remaining_balance=self.balance,
            consumed_credits=credits,
            consumed_total=self.consumed,
            is_cached=False,
        )

    def replenish(self, credits: int, reset_consumed: bool = False) -> None:
        """Replenishes quota credits on subscription renewal or top-up purchase.

        When reset_consumed=True (cycle renewal), resets balance and total_allowance to
        the tier cycle credits and clears consumed=0. When False (top-up), adds credits
        to both balance and total_allowance.
        """
        if credits <= 0:
            raise ValueError(f"Replenish credits must be positive integer, got {credits}")
        now = datetime.now(timezone.utc)
        if reset_consumed:
            self.balance = credits
            self.total_allowance = credits
            self.consumed = 0
            self.last_reset_at = now
        else:
            self.balance += credits
            self.total_allowance += credits
        self.updated_at = now
