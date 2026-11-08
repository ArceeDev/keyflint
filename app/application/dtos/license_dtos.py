"""DTOs for License issuance, verification, activation, and revocation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.domain.entities.license import normalize_domain_host

_VALID_TIERS = ("community", "indie", "agency", "pro", "studio", "lifetime", "despacho_basico", "despacho_pro", "despacho_empresa")
_VALID_ALGOS = ("ed25519", "hmac-sha256", "hmac")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LicenseIssueRequest(BaseModel):
    """Payload to issue a new license key."""

    customer_email: str
    tier: str = "pro"
    max_seats: Optional[int] = Field(default=None, gt=0)
    max_activations: Optional[int] = Field(default=None, gt=0)
    expires_in_days: Optional[int] = Field(default=None, gt=0)
    features: Optional[list[str]] = None
    company: Optional[str] = None
    signing_algorithm: str = "ed25519"
    machine_id: Optional[str] = None
    allowed_domains: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("customer_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        s = (v or "").strip()
        if not s or not _EMAIL_RE.match(s):
            raise ValueError("Invalid customer_email format")
        return s

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        s = (v or "").strip().lower()
        if s not in _VALID_TIERS:
            raise ValueError(f"Invalid tier '{v}'. Must be one of: {', '.join(_VALID_TIERS)}")
        return s

    @field_validator("signing_algorithm")
    @classmethod
    def validate_algo(cls, v: str) -> str:
        s = (v or "ed25519").strip().lower()
        if s not in _VALID_ALGOS:
            raise ValueError(f"Unsupported signing_algorithm '{v}'.")
        return "hmac-sha256" if s == "hmac" else s

    @field_validator("allowed_domains")
    @classmethod
    def validate_allowed_domains(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return None
        normalized: list[str] = []
        for item in v:
            if item is None or (isinstance(item, str) and not item.strip()):
                continue
            norm = normalize_domain_host(item, allow_wildcard=True)
            if not norm:
                raise ValueError(f"Invalid allowed_domains pattern: '{item}'")
            if norm not in normalized:
                normalized.append(norm)
        return normalized or None

    def get_effective_max_seats(self) -> Optional[int]:
        """Returns max_seats or max_activations if specified."""
        if self.max_seats is not None:
            return self.max_seats
        return self.max_activations


class LicenseIssueResponse(BaseModel):
    """Result of license issuance."""

    license_id: str
    license_key: str
    customer_id: str
    customer_email: str
    tier: str
    max_seats: int
    max_activations: int
    expires_at: Optional[datetime] = None
    signature: str
    quota_credits: int


class LicenseVerifyRequest(BaseModel):
    """Payload to verify an existing license."""

    license_key: str
    hardware_id: Optional[str] = None
    domain: Optional[str] = None


class LicenseVerifyResponse(BaseModel):
    """Result of license verification."""

    valid: bool = True
    is_valid: bool = True
    license_id: str
    tier: str
    status: str
    expires_at: Optional[datetime] = None
    features: list[str] = Field(default_factory=list)
    current_activations: int = 0
    max_seats: int = 1
    max_activations: int = 1


class LicenseActivateRequest(BaseModel):
    """Payload to bind a hardware node/machine to a license."""

    license_key: str
    hardware_id: str
    machine_name: Optional[str] = None
    ip_address: Optional[str] = None

    @field_validator("license_key", "hardware_id")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("Field cannot be empty or whitespace")
        return s


class LicenseActivateResponse(BaseModel):
    """Result of machine activation."""

    activated: bool = True
    success: bool = True
    license_id: str
    hardware_id: str
    current_activations: int
    max_seats: int
    max_activations: int
    activated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class LicenseRevokeRequest(BaseModel):
    """Payload to revoke an active license."""

    license_key: str
    reason: str = "administrative_revocation"


class LicenseRevokeResponse(BaseModel):
    """Result of license revocation."""

    success: bool = True
    license_key: str
    status: str = "revoked"
    revoked_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class LicenseNodesRequest(BaseModel):
    """Lists the machines activated on a license (the license key authenticates the caller)."""

    license_key: str = Field(min_length=1)


class LicenseNodeReleaseRequest(BaseModel):
    """Frees the seat held by ``hardware_id`` (e.g. a rebuilt container or devcontainer)."""

    license_key: str = Field(min_length=1)
    hardware_id: str = Field(min_length=1, max_length=256)
