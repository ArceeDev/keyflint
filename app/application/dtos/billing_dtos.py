"""DTOs for Billing, Checkout, Webhook Processing, and Simulator."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


VALID_TIERS = ("community", "pro", "studio", "lifetime")
VALID_PROVIDERS = ("stripe", "lemonsqueezy")


class CheckoutRequest(BaseModel):
    """Payload to initiate a checkout session."""

    customer_email: str = Field(min_length=1)
    tier: str = "pro"
    interval: Optional[str] = "monthly"
    provider: str = "stripe"

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        s = v.strip()
        if not s or "@" not in s:
            raise ValueError("customer_email must be a valid, non-empty email address")
        return s

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in VALID_TIERS:
            raise ValueError(f"Invalid tier '{v}'. Supported tiers: {', '.join(VALID_TIERS)}")
        return s

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        s = v.strip().lower()
        if s not in VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider '{v}'. Supported providers: {', '.join(VALID_PROVIDERS)}"
            )
        return s


class CheckoutResponse(BaseModel):
    """Result of checkout session creation."""

    checkout_url: str
    session_id: str
    customer_email: str
    tier: str
    provider: str = "stripe"
    mode: str = "mock"


class PortalRequest(BaseModel):
    """Payload to generate a customer billing portal URL."""

    customer_email: str = Field(min_length=1)

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        s = v.strip()
        if not s or "@" not in s:
            raise ValueError("customer_email must be a valid, non-empty email address")
        return s


class PortalResponse(BaseModel):
    """Customer management portal session."""

    portal_url: str
    customer_email: str


class WebhookSimulationRequest(BaseModel):
    """Request payload for local mock webhook simulation."""

    provider: str = "stripe"
    event_type: str = "checkout.session.completed"
    customer_email: str = "simulated@acme.ai"
    tier: str = "pro"


class WebhookSimulationResponse(BaseModel):
    """Result returned by simulated webhook execution."""

    processed: bool = True
    event_id: str
    event_type: str
    customer_email: str
    tier: str
    license_key: Optional[str] = None
    license_status: Optional[str] = None


class BillingStatusResponse(BaseModel):
    """Billing and credit utilization status report."""

    license_id: Optional[str] = None
    license_key: Optional[str] = None
    customer_email: Optional[str] = None
    tier: str = "community"
    status: str = "active"
    credit_balance: int = 0
    total_allowance: int = 0
    consumed: int = 0
