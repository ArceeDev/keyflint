"""Telemetry & Audit Trail REST API Router."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.domain.exceptions import LicenseNotFoundError
from app.infrastructure.repositories.sqlite_license_repo import SqliteLicenseRepo
from app.presentation.dependencies import (
    build_response_metadata,
    get_db,
    get_license_repo,
)

router = APIRouter(prefix="/api/v1/telemetry", tags=["Telemetry"])


@router.get("/events")
def list_events(
    http_request: Request,
    license_key: str = Query(..., min_length=1),
    conn: sqlite3.Connection = Depends(get_db),
    license_repo: SqliteLicenseRepo = Depends(get_license_repo),
) -> dict[str, Any]:
    """Returns structured JSON audit trail for activations and quota consumption."""
    license_entity = license_repo.get_by_key(license_key)
    if license_entity is None:
        raise LicenseNotFoundError("License not found.")

    cur_events = conn.execute(
        """
        SELECT id, license_id, event_type, credits_consumed, idempotency_key, metadata_json, timestamp
        FROM usage_events
        WHERE license_id = ?
        ORDER BY timestamp DESC
        LIMIT 100
        """,
        (license_entity.id,),
    )
    events = [dict(r) for r in cur_events.fetchall()]
    activations = [
        {
            "hardware_id": act.hardware_id,
            "machine_name": act.machine_name,
            "activated_at": act.activated_at.isoformat(),
        }
        for act in license_repo.get_activations(license_entity.id)
    ]

    return {
        "success": True,
        "data": {
            "license_id": license_entity.id,
            "tier": license_entity.tier.value,
            "status": license_entity.status.value,
            "events": events,
            "activations": activations,
            "count": len(events),
        },
        "metadata": build_response_metadata(http_request),
    }
