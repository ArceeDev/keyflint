"""Quota Metering, Balance & Replenishment REST API Router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.application.dtos.quota_dtos import (
    QuotaBalanceRequest,
    QuotaDeductRequest,
    QuotaReplenishRequest,
)
from app.application.services.quota_service import QuotaService
from app.presentation.dependencies import (
    build_response_metadata,
    get_quota_service,
    require_admin_access,
)

router = APIRouter(prefix="/api/v1/quota", tags=["Quota"])


@router.post("/deduct")
def deduct_quota(
    request: QuotaDeductRequest,
    http_request: Request,
    response: Response,
    quota_service: QuotaService = Depends(get_quota_service),
) -> dict[str, Any]:
    """Atomically consumes usage credits with paywall protection and idempotency."""
    if request.credits <= 0:
        raise HTTPException(
            status_code=422, detail="Credits to deduct must be a positive integer."
        )

    res = quota_service.deduct(request)
    if res.license_status == "grace_period":
        response.headers["X-Subscription-Warning"] = "Account in payment grace period"

    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


@router.post("/replenish", dependencies=[Depends(require_admin_access)])
def replenish_quota(
    request: QuotaReplenishRequest,
    http_request: Request,
    quota_service: QuotaService = Depends(get_quota_service),
) -> dict[str, Any]:
    """Replenishes or resets billing-cycle credits for a license."""
    if request.credits <= 0:
        raise HTTPException(
            status_code=422, detail="Credits to replenish must be a positive integer."
        )

    res = quota_service.replenish(request)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


@router.get("/balance")
def get_quota_balance(
    http_request: Request,
    license_key: str = Query(..., min_length=1),
    quota_service: QuotaService = Depends(get_quota_service),
) -> dict[str, Any]:
    """Returns remaining credit balance and usage stats for a license."""
    res = quota_service.get_balance(QuotaBalanceRequest(license_key=license_key))
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }
