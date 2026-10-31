"""Cryptographic Signer Port Interface.

100% Pure Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class ICryptoSigner(Protocol):
    """Abstract port for cryptographic token signing and verification."""

    def sign(self, payload: dict[str, Any]) -> str:
        """Computes cryptographic signature string over canonical dictionary payload."""
        ...

    def verify(self, payload: dict[str, Any], signature: str) -> bool:
        """Verifies signature against canonical dictionary payload."""
        ...

    def sign_token(self, payload: dict[str, Any]) -> str:
        """Constructs complete compact token: 'LIC-<TIER>-<BASE64_PAYLOAD>.<BASE64_SIGNATURE>'."""
        ...

    def verify_token(
        self, token: str
    ) -> tuple[bool, Optional[dict[str, Any]], Optional[str]]:
        """Parses and validates token string. Returns (is_valid, decoded_payload, error_code)."""
        ...

    def format_token(
        self, tier: str, payload: dict[str, Any], signature: str
    ) -> str:
        """Constructs compact token from components."""
        ...
