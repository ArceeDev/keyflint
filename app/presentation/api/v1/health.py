"""Health and readiness probe endpoints."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.presentation.dependencies import build_response_metadata, get_db

router = APIRouter(tags=["Health"])


@router.get("/healthz")
def healthz(http_request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "healthy": True,
        "metadata": build_response_metadata(http_request),
    }


@router.get("/readyz")
def readyz(
    http_request: Request,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        conn.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database readiness check failed: {exc}",
        ) from exc
    return {
        "status": "ready",
        "ready": True,
        "metadata": build_response_metadata(http_request),
    }


@router.get("/api/v1/health")
def api_health(http_request: Request) -> dict[str, Any]:
    from app.infrastructure.email.transactional_email_service import TransactionalEmailService

    return {
        "status": "ok",
        "healthy": True,
        "email_provider": TransactionalEmailService().provider,
        "metadata": build_response_metadata(http_request),
    }
