"""DTOs for Quota metering, balance queries, and credit replenishment."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class QuotaDeductRequest(BaseModel):
    """Payload to deduct usage credits."""

    license_key: str
    credits: int = Field(gt=0, default=1)
    idempotency_key: str
    event_type: str = "api_call"
    metadata: Optional[dict[str, Any]] = None


class QuotaDeductResponse(BaseModel):
    """Result of quota deduction."""

    success: bool
    license_id: str
    remaining_balance: int
    consumed_credits: int
    consumed_total: int = 0
    deducted: int = 0
    is_cached: bool = False
    event_id: Optional[str] = None
    transaction_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    license_status: str = "active"


class QuotaRefundRequest(BaseModel):
    """Payload to compensate a previous deduct (e.g. the metered tool failed)."""

    license_key: str
    idempotency_key: str = Field(min_length=1, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=200)


class QuotaRefundResponse(BaseModel):
    """Result of a refund."""

    success: bool
    license_id: str
    refunded: int
    remaining_balance: int
    consumed_total: int = 0
    is_cached: bool = False
    event_id: Optional[str] = None
    idempotency_key: str


class QuotaReplenishRequest(BaseModel):
    """Payload to add credits to a license."""

    license_key: str
    credits: int = Field(gt=0)
    reset_cycle: bool = False


class QuotaReplenishResponse(BaseModel):
    """Result of quota replenishment."""

    success: bool
    license_id: str
    balance: int
    total_allowance: int
    consumed: int = 0


class QuotaBalanceRequest(BaseModel):
    """Query parameters to inspect quota balance."""

    license_key: str


class QuotaBalanceResponse(BaseModel):
    """Current quota balance and lifetime consumption."""

    license_id: str
    balance: int
    credit_balance: int = 0
    total_allowance: int
    consumed: int
    last_reset_at: datetime
