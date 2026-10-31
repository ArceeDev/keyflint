"""License Repository Port Interface.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from app.domain.entities.license import Activation, License, LicenseStatus


@runtime_checkable
class ILicenseRepository(Protocol):
    """Abstract port for license persistence and activation management."""

    def save(self, license_entity: License) -> None:
        """Persists a new license aggregate or updates an existing one."""
        ...

    def get_by_id(self, license_id: str) -> Optional[License]:
        """Finds a license by primary UUID."""
        ...

    def get_by_key(self, license_key: str) -> Optional[License]:
        """Finds a license by cryptographic key string."""
        ...

    def list_by_customer_id(self, customer_id: str) -> list[License]:
        """Lists all licenses belonging to a specific customer."""
        ...

    def update(self, license_entity: License) -> None:
        """Updates mutable state of an existing license."""
        ...

    def update_status(self, license_id: str, status: LicenseStatus) -> None:
        """Updates status of an existing license."""
        ...

    def record_activation(
        self,
        license_id: str,
        hardware_id: str,
        machine_name: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """Registers a node activation for the license. Returns True if created/active."""
        ...

    def get_activations(self, license_id: str) -> list[Activation]:
        """Retrieves all active node activations for a license."""
        ...

    def get_activation(self, license_id: str, hardware_id: str) -> Optional[Activation]:
        """Retrieves specific node activation record."""
        ...

    def count_activations(self, license_id: str) -> int:
        """Returns total active seat count for license."""
        ...

    def record_revocation(self, license_id: str, reason: str) -> None:
        """Persists irreversible revocation entry in revoked_licenses ledger."""
        ...

    def is_revoked(self, license_id: str) -> bool:
        """Checks whether license_id is recorded in revoked_licenses ledger."""
        ...
