"""Payment Provider Webhook Ingestion Router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.application.services.billing_service import BillingService
from app.presentation.dependencies import build_response_metadata, get_billing_service

router = APIRouter(prefix="/api/v1/webhooks", tags=["Webhooks"])


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Ingests Stripe lifecycle webhooks with HMAC-SHA256 signature verification."""
    raw_body = await request.body()
    headers = dict(request.headers)
    result = billing_service.process_webhook(
        provider="stripe",
        raw_body=raw_body,
        headers=headers,
    )
    return {
        "success": True,
        "data": result,
        "metadata": build_response_metadata(request),
    }


@router.post("/lemonsqueezy")
async def lemonsqueezy_webhook(
    request: Request,
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, Any]:
    """Ingests LemonSqueezy lifecycle webhooks with X-Signature HMAC verification."""
    raw_body = await request.body()
    headers = dict(request.headers)
    result = billing_service.process_webhook(
        provider="lemonsqueezy",
        raw_body=raw_body,
        headers=headers,
    )
    return {
        "success": True,
        "data": result,
        "metadata": build_response_metadata(request),
    }
