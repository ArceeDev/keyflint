"""Domain Exceptions for KeyForge.

100% Pure Python Standard Library. Zero external dependencies.
Aligned with RFC 7807 Problem Details.
"""

from typing import Any, Optional


class DomainError(Exception):
    """Base domain exception for all KeyForge business domain errors."""

    code: str = "DOMAIN_ERROR"
    status_code: int = 400

    def __init__(
        self,
        message: str,
        details: Optional[dict[str, Any]] = None,
        status_code: Optional[int] = None,
        code: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        """Serializes error to RFC 7807 compliant dictionary."""
        return {
            "code": self.code,
            "message": self.message,
            "status_code": self.status_code,
            "details": self.details,
        }


class QuotaExceededError(DomainError):
    """Raised when an operation requires more quota credits than available."""

    code = "QUOTA_EXHAUSTED"
    status_code = 402  # HTTP 402 Payment Required


class LicenseExpiredError(DomainError):
    """Raised when attempting to use or verify an expired license key."""

    code = "LICENSE_EXPIRED"
    status_code = 403


class LicenseRevokedError(DomainError):
    """Raised when a license has been explicitly revoked."""

    code = "LICENSE_REVOKED"
    status_code = 403


class LicenseSuspendedError(DomainError):
    """Raised when a license is suspended due to payment delinquency."""

    code = "LICENSE_SUSPENDED"
    status_code = 403


class LicenseNotFoundError(DomainError):
    """Raised when a license key or license ID cannot be found."""

    code = "LICENSE_NOT_FOUND"
    status_code = 404


class CustomerNotFoundError(DomainError):
    """Raised when a customer record cannot be found."""

    code = "CUSTOMER_NOT_FOUND"
    status_code = 404


class InvalidSignatureError(DomainError):
    """Raised when cryptographic signature verification fails or key is tampered."""

    code = "INVALID_SIGNATURE"
    status_code = 401


class SeatLimitExceededError(DomainError):
    """Raised when activating a license on more nodes than allowed."""

    code = "SEAT_LIMIT_EXCEEDED"
    status_code = 409


class NodeLockViolationError(DomainError):
    """Raised when hardware fingerprint does not match licensed machine."""

    code = "NODE_LOCK_VIOLATION"
    status_code = 403


class DuplicateActivationError(DomainError):
    """Raised when a node hardware ID is already registered for this license."""

    code = "DUPLICATE_ACTIVATION"
    status_code = 409


class InvalidLicenseFormatError(DomainError):
    """Raised when a license token string is malformed."""

    code = "INVALID_LICENSE_FORMAT"
    status_code = 400


class IdempotencyConflictError(DomainError):
    """Raised when an idempotency key is reused with conflicting parameters."""

    code = "IDEMPOTENCY_CONFLICT"
    status_code = 409
