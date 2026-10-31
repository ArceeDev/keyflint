"""Customer Domain Entity.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass(slots=True)
class Customer:
    """Represents a registered software purchaser / developer account."""

    id: str
    email: str
    company: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate_email()

    def validate_email(self) -> None:
        """Validates basic email formatting."""
        if not self.email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", self.email.strip()):
            raise ValueError(f"Invalid customer email address: '{self.email}'")

    def update_company(self, company: Optional[str]) -> None:
        """Updates company affiliation."""
        self.company = company.strip() if company else None
        self.updated_at = datetime.now(timezone.utc)
