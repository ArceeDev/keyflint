"""License and Activation Domain Entities & Value Objects.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Optional

from app.domain.exceptions import (
    LicenseExpiredError,
    LicenseRevokedError,
    LicenseSuspendedError,
    SeatLimitExceededError,
)


class Tier(StrEnum):
    """KeyFlint Commercial Subscription and License Tiers."""

    COMMUNITY = "community"
    INDIE = "indie"
    AGENCY = "agency"
    PRO = "pro"
    STUDIO = "studio"
    LIFETIME = "lifetime"

    @property
    def default_allowance(self) -> int:
        match self:
            case Tier.COMMUNITY:
                return 25
            case Tier.INDIE:
                return 10_000
            case Tier.AGENCY:
                return 50_000
            case Tier.PRO:
                return 500
            case Tier.STUDIO:
                return 5_000
            case Tier.LIFETIME:
                return 10_000

    @property
    def default_max_activations(self) -> int:
        match self:
            case Tier.COMMUNITY:
                return 1
            case Tier.INDIE:
                return 3
            case Tier.AGENCY:
                return 25
            case Tier.PRO:
                return 3
            case Tier.STUDIO:
                return 25
            case Tier.LIFETIME:
                return 3

    @property
    def default_features(self) -> tuple[str, ...]:
        match self:
            case Tier.COMMUNITY:
                return ("core",)
            case Tier.INDIE:
                return ("core", "cli_offline", "telemetry_sync", "lifetime_v1")
            case Tier.AGENCY:
                return ("core", "cli_offline", "telemetry_sync", "multi_tenant", "priority_support")
            case Tier.PRO:
                return ("core", "cli_offline", "telemetry_sync")
            case Tier.STUDIO:
                return ("core", "cli_offline", "telemetry_sync", "multi_tenant", "priority_webhook")
            case Tier.LIFETIME:
                return ("core", "cli_offline", "telemetry_sync", "self_hosted")

    @property
    def default_expires_in_days(self) -> Optional[int]:
        match self:
            case Tier.COMMUNITY | Tier.PRO | Tier.STUDIO:
                return 365
            case Tier.INDIE | Tier.AGENCY | Tier.LIFETIME:
                return None


class LicenseStatus(StrEnum):
    """Lifecycle status states for a license key."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    REVOKED = "revoked"
    GRACE_PERIOD = "grace_period"


@dataclass(slots=True)
class Activation:
    """Represents a node or machine hardware lock activation."""

    id: str
    license_id: str
    hardware_id: str
    machine_name: Optional[str] = None
    ip_address: Optional[str] = None
    activated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.hardware_id or not self.hardware_id.strip():
            raise ValueError("hardware_id must not be empty or whitespace")
        self.hardware_id = self.hardware_id.strip().lower()


@dataclass(slots=True)
class License:
    """Core domain aggregate entity representing a cryptographic software license."""

    id: str
    customer_id: str
    license_key: str
    tier: Tier
    status: LicenseStatus = LicenseStatus.ACTIVE
    max_seats: int = 1
    current_activations: int = 0
    expires_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signature: str = ""
    features: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def max_activations(self) -> int:
        """Alias for max_seats."""
        return self.max_seats

    @max_activations.setter
    def max_activations(self, val: int) -> None:
        self.max_seats = val

    def is_expired(self, at: Optional[datetime] = None) -> bool:
        """Evaluates whether the license has passed its expiration timestamp."""
        if self.expires_at is None:
            return False
        ref = at or datetime.now(timezone.utc)
        return ref > self.expires_at

    def is_active(self, at: Optional[datetime] = None) -> bool:
        """Evaluates whether the license is currently active and unexpired."""
        if self.status != LicenseStatus.ACTIVE:
            return False
        return not self.is_expired(at)

    def can_activate(self, at: Optional[datetime] = None) -> bool:
        """Determines if a new machine seat activation is permissible."""
        if self.status not in (LicenseStatus.ACTIVE, LicenseStatus.GRACE_PERIOD):
            return False
        return not self.is_expired(at) and self.current_activations < self.max_seats

    def has_feature(self, feature_name: str) -> bool:
        """Checks if the license contains entitlement for a specific capability."""
        return feature_name in self.features

    def matches_domain(self, domain: Optional[str]) -> bool:
        """Checks whether a caller domain satisfies optional allowed_domains metadata."""
        return matches_allowed_domains(self.metadata.get("allowed_domains"), domain)

    def record_activation(self) -> None:
        """Validates invariants and increments active seat count."""
        if self.status == LicenseStatus.REVOKED:
            raise LicenseRevokedError(f"Cannot activate revoked license {self.id}")
        if self.status == LicenseStatus.SUSPENDED:
            raise LicenseSuspendedError(f"Cannot activate suspended license {self.id}")
        if self.status == LicenseStatus.EXPIRED or self.is_expired():
            raise LicenseExpiredError(f"Cannot activate expired license {self.id}")
        if self.current_activations >= self.max_seats:
            raise SeatLimitExceededError(
                f"Seat limit of {self.max_seats} reached for license {self.id}",
                details={
                    "license_id": self.id,
                    "max_seats": self.max_seats,
                    "max_activations": self.max_seats,
                    "current_activations": self.current_activations,
                },
            )
        self.current_activations += 1

    def revoke(self, reason: str = "administrative_revocation") -> None:
        """Transitions license to revoked status."""
        self.status = LicenseStatus.REVOKED
        self.metadata["revocation_reason"] = reason
        self.metadata["revoked_at"] = datetime.now(timezone.utc).isoformat()

    def suspend(self) -> None:
        """Suspends active license privileges."""
        self.status = LicenseStatus.SUSPENDED

    def reinstate(self) -> None:
        """Reinstates suspended license to active status if not expired."""
        if self.is_expired():
            self.status = LicenseStatus.EXPIRED
        else:
            self.status = LicenseStatus.ACTIVE

    def extend_expiration(self, days: int) -> None:
        """Extends expiration timestamp by specified number of days."""
        now = datetime.now(timezone.utc)
        base = self.expires_at if (self.expires_at and self.expires_at > now) else now
        self.expires_at = base + timedelta(days=days)
        if self.status in (LicenseStatus.EXPIRED, LicenseStatus.GRACE_PERIOD):
            self.status = LicenseStatus.ACTIVE


def normalize_domain_host(raw: Optional[str], *, allow_wildcard: bool = False) -> Optional[str]:
    """Normalizes a hostname (optional :port, trailing FQDN dot, and IDNA punycode).

    Returns lowercase ASCII hostname (or '*.domain.tld' when allow_wildcard=True),
    or None if malformed or degenerate (e.g. '*', '*.', URL path/userinfo).
    """
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or any(ch in s for ch in ("/", "\\", "@", "?", "#", " ", "\t", "\r", "\n")):
        return None

    wildcard = False
    if s.startswith("*."):
        if not allow_wildcard:
            return None
        wildcard = True
        s = s[2:]
    elif "*" in s:
        return None

    if ":" in s:
        host_part, port_part = s.rsplit(":", 1)
        if not port_part.isdigit():
            return None
        port_num = int(port_part)
        if port_num < 1 or port_num > 65535:
            return None
        s = host_part

    s = s.rstrip(".")
    if not s or s.startswith(".") or ".." in s:
        return None

    labels = s.split(".")
    if wildcard and len(labels) < 2:
        return None

    ascii_labels: list[str] = []
    for label in labels:
        if not label:
            return None
        try:
            enc = label.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None
        if not enc or any(not (ch.isalnum() or ch == "-") for ch in enc) or enc.startswith("-") or enc.endswith("-"):
            return None
        ascii_labels.append(enc)

    normalized = ".".join(ascii_labels)
    return f"*.{normalized}" if wildcard else normalized


def matches_allowed_domains(allowed: Any, domain: Optional[str]) -> bool:
    """Evaluates whether domain satisfies an optional allowed_domains list."""
    if not allowed:
        return True
    if not isinstance(allowed, (list, tuple, set)):
        return False
    candidate = normalize_domain_host(domain, allow_wildcard=False)
    if not candidate:
        return False
    for pattern in allowed:
        if not isinstance(pattern, str):
            continue
        pat = normalize_domain_host(pattern, allow_wildcard=True)
        if not pat:
            continue
        if pat == candidate:
            return True
        if pat.startswith("*."):
            suffix = pat[2:]
            if suffix and "." in suffix and (
                candidate == suffix or candidate.endswith("." + suffix)
            ):
                return True
    return False
