"""Customer Repository Port Interface.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from app.domain.entities.customer import Customer


@runtime_checkable
class ICustomerRepository(Protocol):
    """Abstract port for customer profile persistence."""

    def save(self, customer: Customer) -> None:
        """Persists a new customer record."""
        ...

    def get_by_id(self, customer_id: str) -> Optional[Customer]:
        """Finds a customer by primary UUID."""
        ...

    def get_by_email(self, email: str) -> Optional[Customer]:
        """Finds a customer by unique email address."""
        ...

    def update(self, customer: Customer) -> None:
        """Updates customer profile details."""
        ...

    def delete(self, customer_id: str) -> bool:
        """Deletes customer by primary UUID. Returns True if deleted."""
        ...

    def list_customers(self, limit: int = 100, offset: int = 0) -> list[Customer]:
        """Lists registered customers with pagination."""
        ...
