"""Billing, Checkout, Simulator & Customer Portal Router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.application.dtos.billing_dtos import (
    CheckoutRequest,
    PortalRequest,
    WebhookSimulationRequest,
)
from app.application.services.billing_service import BillingService
from app.config import get_settings
from app.presentation.dependencies import build_response_metadata, get_billing_service

router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


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
