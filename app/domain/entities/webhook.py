"""Webhook Record Domain Entity for Idempotency Ledger.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class WebhookRecord:
    """Tracks received payment provider webhooks for replay protection and idempotency."""

    id: str
    event_id: str
    provider: str  # 'stripe' | 'lemonsqueezy'
    event_type: str
    payload_hash: str
    status: str = "processed"  # 'processed' | 'failed' | 'ignored'
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.provider not in ("stripe", "lemonsqueezy"):
            raise ValueError(f"Unsupported webhook provider '{self.provider}'")
        if self.status not in ("processed", "failed", "ignored"):
            raise ValueError(f"Invalid webhook status '{self.status}'")
