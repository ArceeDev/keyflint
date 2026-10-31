"""HMAC-SHA256 Symmetric Signer & Verifier.

Provides constant-time verification to prevent timing attack side channels.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any, Optional


def b64url_encode(data: bytes) -> str:
    """Encode bytes to URL-safe base64 string without trailing padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


_B64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def b64url_decode(s: str) -> bytes:
    """Decode unpadded URL-safe base64 string to bytes with strict character set validation."""
    if not isinstance(s, str) or not _B64URL_PATTERN.match(s):
        raise ValueError("Invalid Base64URL string: contains illegal characters or whitespace.")
    pad_len = (4 - len(s) % 4) % 4
    return base64.b64decode((s + "=" * pad_len).encode("ascii"), altchars=b"-_", validate=True)


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic UTF-8 JSON representation with sort_keys=True and compact separators."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class HmacSha256Signer:
    """Symmetric HMAC-SHA256 signer.

    Ideal for server-side token validation, webhook verification, and internal session grants.
    """

    def __init__(self, secret_key: Optional[bytes | str] = None):
        if secret_key is None:
            try:
                from app.config import get_settings
                secret_key = get_settings().SECRET_KEY
            except Exception:
                secret_key = "default_secret_key_at_least_16_bytes_long"
        if isinstance(secret_key, str):
            self.secret_bytes = secret_key.encode("utf-8")
        else:
            self.secret_bytes = bytes(secret_key)
        if len(self.secret_bytes) < 16:
            raise ValueError("HMAC secret key must be at least 16 bytes for security.")

    def sign_bytes(self, data: bytes) -> bytes:
        """Computes 32-byte HMAC-SHA256 digest."""
        return hmac.new(self.secret_bytes, data, hashlib.sha256).digest()

    def verify_bytes(self, signature: bytes, data: bytes) -> bool:
        """Validates signature using constant-time comparison."""
        expected_sig = self.sign_bytes(data)
        return hmac.compare_digest(expected_sig, signature)

    def sign(self, payload: dict[str, Any]) -> str:
        """Signs canonical JSON dictionary and returns unpadded base64url signature."""
        canon_bytes = canonical_json_bytes(payload)
        sig_bytes = self.sign_bytes(canon_bytes)
        return b64url_encode(sig_bytes)

    def verify(self, payload: dict[str, Any], signature: str) -> bool:
        """Validates unpadded base64url signature in constant time."""
        try:
            expected = self.sign(payload)
            return hmac.compare_digest(expected, signature)
        except Exception:
            return False

    def format_token(self, tier: str, payload: dict[str, Any], signature: str) -> str:
        """Emits token in format: LIC-<TIER>-<BASE64URL_PAYLOAD>.<BASE64URL_SIGNATURE>."""
        canon_bytes = canonical_json_bytes(payload)
        payload_b64 = b64url_encode(canon_bytes)
        return f"LIC-{tier.upper()}-{payload_b64}.{signature}"

    def sign_token(self, payload: dict[str, Any]) -> str:
        """Computes signature and emits full token."""
        tier = str(payload.get("tier", "community")).upper()
        sig_b64 = self.sign(payload)
        return self.format_token(tier, payload, sig_b64)

    def verify_token(
        self, token: str
    ) -> tuple[bool, Optional[dict[str, Any]], Optional[str]]:
        """Parses and validates a full HMAC license token string."""
        if not token or not isinstance(token, str):
            return False, None, "ERR_EMPTY_TOKEN"

        if "." not in token:
            return False, None, "ERR_INVALID_TOKEN_FORMAT"

        parts = token.split(".")
        if len(parts) != 2:
            return False, None, "ERR_INVALID_TOKEN_FORMAT"

        header_part, sig_b64 = parts
        if not header_part.startswith("LIC-"):
            return False, None, "ERR_INVALID_TOKEN_PREFIX"

        subparts = header_part.split("-", 2)
        if len(subparts) != 3:
            return False, None, "ERR_INVALID_TOKEN_FORMAT"

        _, token_tier, payload_b64 = subparts
        try:
            payload_bytes = b64url_decode(payload_b64)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return False, None, "ERR_MALFORMED_PAYLOAD"

        if not isinstance(payload, dict):
            return False, None, "ERR_INVALID_PAYLOAD_STRUCTURE"

        try:
            sig_bytes = b64url_decode(sig_b64)
            if len(sig_bytes) != 32 or not self.verify_bytes(sig_bytes, payload_bytes):
                return False, payload, "ERR_SIGNATURE_TAMPERED"
        except Exception:
            return False, payload, "ERR_SIGNATURE_TAMPERED"

        tier_val = payload.get("tier")
        if not isinstance(tier_val, str) or tier_val.lower() != token_tier.lower():
            return False, payload, "ERR_TIER_MISMATCH"

        expires_at = payload.get("expires_at")
        if expires_at is not None:
            if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
                return False, payload, "ERR_MALFORMED_EXPIRATION"
            if int(time.time()) > expires_at:
                return False, payload, "ERR_LICENSE_EXPIRED"

        return True, payload, None
