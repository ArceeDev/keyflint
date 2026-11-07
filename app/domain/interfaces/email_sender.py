"""Domain interface for transactional email notifications."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LicenseEmailPayload:
    """Carries customer and license details for transactional delivery."""
    recipient_email: str
    tier: str
    license_key: str
    token: str
    public_key_hex: str
    seats: int
    credits: int
    expires_at: Optional[str] = None
    download_url: Optional[str] = None


class IEmailSender(ABC):
    """Port for sending transactional emails across infrastructure providers."""

    @abstractmethod
    def send_license_issued(self, payload: LicenseEmailPayload) -> bool:
        """Dispatches license activation email with signed Ed25519 token."""
        raise NotImplementedError

    @abstractmethod
    def send_quota_replenished(
        self,
        recipient_email: str,
        license_key: str,
        added_credits: int,
        new_balance: int,
    ) -> bool:
        """Dispatches quota cycle replenishment notification."""
        raise NotImplementedError

    def send_ops_alert(self, recipient_email: str, subject: str, text_body: str) -> bool:
        """Plain-text incident alert to the operator. Optional for implementations."""
        return False

    def send_portal_magic_link(self, recipient_email: str, link: str, ttl_minutes: int) -> bool:
        """Single-use customer portal sign-in link. Optional for implementations."""
        return False

    def send_credits_depleted(self, recipient_email: str, license_key: str, *, trial: bool, topup_url: str,
                              topup_eur: int, topup_credits: int) -> bool:
        """Retention email when the credits run out with a one-click top-up link. Optional."""
        return False
