"""Webhook Repository Port Interface.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from app.domain.entities.webhook import WebhookRecord


@runtime_checkable
class IWebhookRepository(Protocol):
    """Abstract port for webhook event tracking and replay deduplication."""

    def save(self, record: WebhookRecord) -> None:
        """Records a processed webhook event."""
        ...

    def get_by_event_id(self, event_id: str) -> Optional[WebhookRecord]:
        """Retrieves webhook record by provider's event ID."""
        ...

    def is_processed(self, event_id: str) -> bool:
        """Fast check to verify if a webhook event ID has already been executed."""
        ...
