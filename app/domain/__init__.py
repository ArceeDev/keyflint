"""KeyForge Domain Layer Package Root.

100% Pure Python Standard Library. Zero external dependencies.
"""

from app.domain.entities import (
    Activation,
    CreditDeductResult,
    Customer,
    DeductResult,
    License,
    LicenseStatus,
    QuotaBalance,
    QuotaLedger,
    Tier,
    UsageEvent,
    WebhookRecord,
)
from app.domain.exceptions import (
    CustomerNotFoundError,
    DomainError,
    DuplicateActivationError,
    IdempotencyConflictError,
    InvalidLicenseFormatError,
    InvalidSignatureError,
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseRevokedError,
    LicenseSuspendedError,
    NodeLockViolationError,
    QuotaExceededError,
    SeatLimitExceededError,
)
from app.domain.interfaces import (
    ICryptoSigner,
    ICustomerRepository,
    ILicenseRepository,
    IQuotaRepository,
    IWebhookRepository,
)

__all__ = [
    # Entities & Enums
    "Tier",
    "LicenseStatus",
    "Activation",
    "License",
    "Customer",
    "QuotaLedger",
    "QuotaBalance",
    "CreditDeductResult",
    "DeductResult",
    "UsageEvent",
    "WebhookRecord",
    # Exceptions
    "DomainError",
    "QuotaExceededError",
    "LicenseExpiredError",
    "LicenseRevokedError",
    "LicenseSuspendedError",
    "LicenseNotFoundError",
    "CustomerNotFoundError",
    "InvalidSignatureError",
    "SeatLimitExceededError",
    "NodeLockViolationError",
    "DuplicateActivationError",
    "InvalidLicenseFormatError",
    "IdempotencyConflictError",
    # Interfaces
    "ILicenseRepository",
    "ICustomerRepository",
    "IQuotaRepository",
    "IWebhookRepository",
    "ICryptoSigner",
]
