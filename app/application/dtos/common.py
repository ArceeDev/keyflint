"""Common DTOs and RFC 7807 problem details envelopes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ResponseMetadata(BaseModel):
    """Metadata envelope included in all API responses."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ErrorDetails(BaseModel):
    """RFC 7807 aligned error object."""

    code: str
    message: str
    status_code: int = 400
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Unified error response model."""

    success: bool = False
    error: ErrorDetails
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)


class SuccessResponse(BaseModel, Generic[T]):
    """Unified successful response model wrapping payload data."""

    success: bool = True
    data: T
    metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
