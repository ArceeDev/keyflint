"""Billing, Checkout, Simulator & Customer Portal Router."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from app.application.dtos.billing_dtos import (
    CheckoutRequest,
    CustomerPortalLookupRequest,
    PortalRedeemRequest,
    PortalRequest,
    WebhookSimulationRequest,
)
from app.application.services.billing_service import BillingService
from app.config import get_settings
from pydantic import BaseModel, Field

from app.presentation.dependencies import (
    build_response_metadata,
    get_billing_service,
    require_admin_access,
)

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])
logger = logging.getLogger("keyflint.billing")


@router.post("/checkout")
def create_checkout(
    request: CheckoutRequest,
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Generates a checkout session for tier subscription or license purchase."""
    res = billing_service.create_checkout_session(request)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


@router.get("/checkout/{session_id}")
def get_mock_checkout_session(
    session_id: str,
    http_request: Request,
) -> dict[str, Any]:
    """Resolves local mock checkout redirect sessions for zero-credential testing."""
    settings = get_settings()
    if settings.BILLING_MODE.strip().lower() == "live":
        raise HTTPException(status_code=404, detail="Mock checkout sessions are disabled in live billing mode.")
    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "mode": "mock",
            "status": "open",
            "instructions": "Use POST /api/v1/billing/simulate-webhook to complete simulated payment provisioning.",
        },
        "metadata": build_response_metadata(http_request),
    }


@router.get("/checkout/{session_id}/license")
def reveal_checkout_license(
    session_id: str,
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Success page: the license bought in this Stripe Checkout session (short-lived, see config)."""
    return {
        "success": True,
        "data": billing_service.reveal_checkout_license(session_id),
        "metadata": build_response_metadata(http_request),
    }


@router.post("/portal")
def create_portal(
    request: PortalRequest,
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Generates customer billing management portal redirect session."""
    res = billing_service.create_portal_session(request)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


@router.get("/portal/{session_id}")
def get_mock_portal_session(
    session_id: str,
    http_request: Request,
) -> dict[str, Any]:
    """Resolves local mock customer billing portal sessions."""
    settings = get_settings()
    if settings.BILLING_MODE.strip().lower() == "live":
        raise HTTPException(status_code=404, detail="Mock portal sessions are disabled in live billing mode.")
    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "mode": "mock",
            "status": "active",
        },
        "metadata": build_response_metadata(http_request),
    }


@router.post("/simulate-webhook")
def simulate_webhook(
    request: WebhookSimulationRequest,
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Local simulation test harness: disabled in production or live billing mode."""
    settings = get_settings()
    if (
        settings.ENVIRONMENT.strip().lower() == "production"
        or settings.BILLING_MODE.strip().lower() == "live"
    ):
        raise HTTPException(
            status_code=403,
            detail="Webhook simulator is disabled in production and live billing mode.",
        )

    res = billing_service.simulate_webhook(request)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


@router.get("/status")
def get_billing_status(
    http_request: Request,
    license_key: str = Query(..., min_length=1),
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Reports credit utilization, quota allowances, and tier status."""
    res = billing_service.get_billing_status(license_key)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


@router.post("/portal/lookup")
def lookup_customer_portal(
    request: CustomerPortalLookupRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Self-service buyer portal.

    - License key: returns that license (possession of the key is the proof).
    - Email: never returns data. If the buyer exists, a single-use link is emailed to that inbox.
      The response is identical whether or not the email exists (no account enumeration).
    """
    if "@" in request.query:
        target = billing_service.request_portal_magic_link(request.query)
        if target is not None:
            background_tasks.add_task(billing_service.send_portal_magic_link, *target)
        return {
            "success": True,
            "data": {
                "magic_link_sent": True,
                "expires_in_seconds": get_settings().PORTAL_LINK_TTL_SECONDS,
                "message": "If this email has KeyFlint licenses, a one-time portal link is on its way.",
            },
            "metadata": build_response_metadata(http_request),
        }
    res = billing_service.lookup_customer_licenses(request)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


class TrialRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    source: str | None = Field(default=None, max_length=40)


class TopupRequest(BaseModel):
    license_key: str = Field(min_length=20, max_length=1024)
    amount_cents: int
    currency: str = Field(default="eur", max_length=3)
    return_url: str | None = Field(default=None, max_length=300)


@router.post("/topup")
def create_topup_checkout(
    request: TopupRequest,
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Pay-as-you-go: Stripe Checkout that adds credits to this same license (the key does not change)."""
    from app.presentation.middlewares import rate_limiter

    tag = hashlib.sha256(request.license_key.strip().encode()).hexdigest()[:16]
    allowed, _, _ = rate_limiter.check(f"topup:{tag}", 10, 3600)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many top-up attempts. Try again in an hour.")
    res = billing_service.create_topup_checkout(
        request.license_key, request.amount_cents, request.currency, request.return_url
    )
    return {"success": True, "data": res, "metadata": build_response_metadata(http_request)}


@router.get("/topup/{session_id}")
def get_topup_status(
    session_id: str,
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Return page: pending until the Stripe webhook applies the credits, then the new balance."""
    return {
        "success": True,
        "data": billing_service.topup_status(session_id),
        "metadata": build_response_metadata(http_request),
    }


@router.post("/trial")
def request_trial_license(
    request: TrialRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Self-serve free trial: one Community license per email, sent only to that inbox.

    The response never contains the key and is identical whether a license was issued or the email
    already had one (no account enumeration, no harvesting keys with fake addresses).
    """
    from app.application.dtos.license_dtos import LicenseIssueRequest
    from app.presentation.middlewares import rate_limiter

    try:
        email = LicenseIssueRequest(customer_email=request.email, tier="community").customer_email
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid email address.") from None
    settings = get_settings()
    if settings.TRIAL_ENABLED:
        allowed, _, _ = rate_limiter.check("trial:daily", max(0, settings.TRIAL_DAILY_CAP), 86400)
    else:
        allowed = True  # the service answers TRIAL_UNAVAILABLE
    if allowed:
        key = billing_service.request_trial_license(email, request.source)
        if key:
            background_tasks.add_task(billing_service.deliver_license_email, key, email)
    else:
        logger.warning("Trial daily cap reached")
    return {
        "success": True,
        "data": {
            "trial_requested": True,
            "message": "If this email has no KeyFlint license yet, a free trial license is on its way.",
        },
        "metadata": build_response_metadata(http_request),
    }


@router.post("/portal/redeem")
def redeem_customer_portal_link(
    request: PortalRedeemRequest,
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Consumes a single-use emailed portal link (POST, so mail scanners prefetching GET cannot burn it)."""
    res = billing_service.redeem_portal_magic_link(request.token)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


class ResendLicenseEmailRequest(BaseModel):
    license_key: str = Field(..., min_length=8)
    to: str | None = Field(default=None, description="Override recipient (defaults to the license owner).")


@router.post("/resend-license-email", dependencies=[Depends(require_admin_access)])
def resend_license_email(
    request: ResendLicenseEmailRequest,
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Admin: re-sends the license email and returns the recorded delivery status."""
    ok = billing_service.deliver_license_email(request.license_key.strip(), recipient=request.to)
    return {
        "success": ok,
        "data": {"email_delivered": ok},
        "metadata": build_response_metadata(http_request),
    }


@router.post("/retry-failed-license-emails", dependencies=[Depends(require_admin_access)])
def retry_failed_license_emails(
    http_request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Admin: retries every license email whose last attempt failed."""
    return {
        "success": True,
        "data": billing_service.retry_failed_license_emails(),
        "metadata": build_response_metadata(http_request),
    }
