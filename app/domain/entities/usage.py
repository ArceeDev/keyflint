"""Usage Event Domain Entity for Audit Logs & Telemetry.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class UsageEvent:
    """Immutable audit record representing a discrete quota consumption event."""

    id: str
    license_id: str
    event_type: str
    credits_consumed: int
    idempotency_key: str
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.credits_consumed < 0:
            raise ValueError("credits_consumed must not be negative")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty or whitespace")
        if not self.license_id or not self.license_id.strip():
            raise ValueError("license_id must not be empty or whitespace")
        if not self.event_type or not self.event_type.strip():
            raise ValueError("event_type must not be empty or whitespace")
