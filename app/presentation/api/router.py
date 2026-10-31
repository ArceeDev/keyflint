"""Main API Router aggregating all sub-routers."""

from __future__ import annotations

from fastapi import APIRouter

from app.presentation.api.v1.billing import router as billing_router
from app.presentation.api.v1.health import router as health_router
from app.presentation.api.v1.licenses import router as licenses_router
from app.presentation.api.v1.quota import router as quota_router
from app.presentation.api.v1.telemetry import router as telemetry_router
from app.presentation.api.v1.webhooks import router as webhooks_router

api_router = APIRouter()

# Include health checks at root (/healthz, /readyz)
api_router.include_router(health_router)

# Include v1 resource routers
api_router.include_router(licenses_router)
api_router.include_router(quota_router)
api_router.include_router(webhooks_router)
api_router.include_router(billing_router)
api_router.include_router(telemetry_router)
