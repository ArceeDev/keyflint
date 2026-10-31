"""Ed25519 Asymmetric Signer & Verifier.

Implements RFC 8032 with automatic fallback to pure Python curve math when
cryptography is not installed.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from typing import Any, Optional

# ----------------------------------------------------------------------
# Pure Python RFC 8032 Fallback Core (Extended Twisted Edwards Coordinates)
# ----------------------------------------------------------------------
_B_PARAM = 256
_Q_PARAM = 2**255 - 19
_L_PARAM = 2**252 + 27742317777372353535851937790883648493

ExtPoint = tuple[int, int, int, int]
_EXT_ZERO: ExtPoint = (0, 1, 1, 0)


def _h(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _inv(x: int) -> int:
    return pow(x, _Q_PARAM - 2, _Q_PARAM)


_D_PARAM = (-121665 * _inv(121666)) % _Q_PARAM
_D2_PARAM = (2 * _D_PARAM) % _Q_PARAM
_I_PARAM = pow(2, (_Q_PARAM - 1) // 4, _Q_PARAM)


def _xrecover(y: int) -> int:
    u = (y * y - 1) % _Q_PARAM
    v = (_D_PARAM * y * y + 1) % _Q_PARAM
    xx = (u * _inv(v)) % _Q_PARAM
    x = pow(xx, (_Q_PARAM + 3) // 8, _Q_PARAM)
    if (x * x - xx) % _Q_PARAM != 0:
        x = (x * _I_PARAM) % _Q_PARAM
    if (x * x - xx) % _Q_PARAM != 0:
        raise ValueError("Coordinate y does not correspond to a valid Ed25519 curve point.")
    if x & 1:
        x = _Q_PARAM - x
    return x


_BY_PARAM = (4 * _inv(5)) % _Q_PARAM
_BX_PARAM = _xrecover(_BY_PARAM)
_BASE_POINT = (_BX_PARAM, _BY_PARAM)
_BASE_EXT: ExtPoint = (_BX_PARAM, _BY_PARAM, 1, (_BX_PARAM * _BY_PARAM) % _Q_PARAM)


def _ext_add(p1: ExtPoint, p2: ExtPoint) -> ExtPoint:
    """RFC 8032 §5.1.4 complete extended coordinate addition (zero modular inversions)."""
    x1, y1, z1, t1 = p1
    x2, y2, z2, t2 = p2
    a = ((y1 - x1) * (y2 - x2)) % _Q_PARAM
    b = ((y1 + x1) * (y2 + x2)) % _Q_PARAM
    c = (t1 * _D2_PARAM * t2) % _Q_PARAM
    d = (2 * z1 * z2) % _Q_PARAM
    e = (b - a) % _Q_PARAM
    f = (d - c) % _Q_PARAM
    g = (d + c) % _Q_PARAM
    h = (b + a) % _Q_PARAM
    return ((e * f) % _Q_PARAM, (g * h) % _Q_PARAM, (f * g) % _Q_PARAM, (e * h) % _Q_PARAM)


def _ext_dbl(p: ExtPoint) -> ExtPoint:
    """RFC 8032 §5.1.4 extended coordinate point doubling (zero modular inversions)."""
    x1, y1, z1, _ = p
    a = (x1 * x1) % _Q_PARAM
    b = (y1 * y1) % _Q_PARAM
    c = (2 * z1 * z1) % _Q_PARAM
    h = (a + b) % _Q_PARAM
    xy = x1 + y1
    e = (h - xy * xy) % _Q_PARAM
    g = (a - b) % _Q_PARAM
    f = (c + g) % _Q_PARAM
    return ((e * f) % _Q_PARAM, (g * h) % _Q_PARAM, (f * g) % _Q_PARAM, (e * h) % _Q_PARAM)


def _ext_scalarmult(pt: ExtPoint, e: int) -> ExtPoint:
    """Iterative double-and-add scalar multiplication in extended coordinates."""
    res = _EXT_ZERO
    addend = pt
    scalar = e
    while scalar > 0:
        if scalar & 1:
            res = _ext_add(res, addend)
        addend = _ext_dbl(addend)
        scalar >>= 1
    return res


def _ext_eq(p1: ExtPoint, p2: ExtPoint) -> bool:
    """Projective equality check without modular inversion."""
    x1, y1, z1, _ = p1
    x2, y2, z2, _ = p2
    return (x1 * z2 - x2 * z1) % _Q_PARAM == 0 and (y1 * z2 - y2 * z1) % _Q_PARAM == 0


def _encodepoint_ext(pt: ExtPoint) -> bytes:
    x_proj, y_proj, z_proj, _ = pt
    zi = _inv(z_proj)
    x = (x_proj * zi) % _Q_PARAM
    y = (y_proj * zi) % _Q_PARAM
    encoded = y | ((x & 1) << 255)
    return encoded.to_bytes(32, "little")


def _decodepoint_ext(s: bytes) -> ExtPoint:
    """Strict RFC 8032 §5.1.3 canonical point decoding."""
    if len(s) != 32:
        raise ValueError("Encoded Ed25519 point must be exactly 32 bytes.")
    raw = int.from_bytes(s, "little")
    y = raw & ((1 << 255) - 1)
    sign_bit = (raw >> 255) & 1
    if y >= _Q_PARAM:
        raise ValueError("Non-canonical y coordinate (>= p).")

    x = _xrecover(y)
    if x == 0 and sign_bit == 1:
        raise ValueError("Invalid point encoding: x=0 with sign bit 1.")
    if (x & 1) != sign_bit:
        x = _Q_PARAM - x

    if (-x * x + y * y - 1 - _D_PARAM * x * x * y * y) % _Q_PARAM != 0:
        raise ValueError("Decoded point does not satisfy Ed25519 curve equation.")

    return (x, y, 1, (x * y) % _Q_PARAM)


def _decodepoint(s: bytes) -> tuple[int, int]:
    """Affine wrapper around strict RFC 8032 point decoding."""
    x, y, _, _ = _decodepoint_ext(s)
    return (x, y)


def _clamp_scalar(digest_32: bytes) -> int:
    clamped = bytearray(digest_32[:32])
    clamped[0] &= 248
    clamped[31] &= 127
    clamped[31] |= 64
    return int.from_bytes(clamped, "little")


def _pure_publickey(sk: bytes) -> bytes:
    if len(sk) != 32:
        raise ValueError("Ed25519 private key seed must be 32 bytes.")
    h = _h(sk)
    a = _clamp_scalar(h[:32])
    a_pt = _ext_scalarmult(_BASE_EXT, a)
    return _encodepoint_ext(a_pt)


def _pure_sign(m: bytes, sk: bytes, pk: bytes) -> bytes:
    h = _h(sk)
    a = _clamp_scalar(h[:32])
    r = int.from_bytes(_h(h[32:] + m), "little") % _L_PARAM
    r_bytes = _encodepoint_ext(_ext_scalarmult(_BASE_EXT, r))
    k_scalar = int.from_bytes(_h(r_bytes + pk + m), "little") % _L_PARAM
    s_scalar = (r + k_scalar * a) % _L_PARAM
    return r_bytes + s_scalar.to_bytes(32, "little")


def _pure_verify(sig: bytes, m: bytes, pk: bytes) -> bool:
    if len(sig) != 64 or len(pk) != 32:
        return False
    s_scalar = int.from_bytes(sig[32:], "little")
    if s_scalar >= _L_PARAM:
        return False
    try:
        r_ext = _decodepoint_ext(sig[:32])
        a_ext = _decodepoint_ext(pk)
    except ValueError:
        return False

    h_scalar = int.from_bytes(_h(sig[:32] + pk + m), "little") % _L_PARAM
    sb = _ext_scalarmult(_BASE_EXT, s_scalar)
    rha = _ext_add(r_ext, _ext_scalarmult(a_ext, h_scalar))
    return _ext_eq(sb, rha)


# ----------------------------------------------------------------------
# Serialization Helpers
# ----------------------------------------------------------------------
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


_KID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _validate_kid(kid: str) -> str:
    kid = kid.strip()
    if not _KID_RE.match(kid):
        raise ValueError(f"Invalid kid {kid!r}: use 1-64 chars [A-Za-z0-9._-].")
    return kid


def parse_key_ring(raw: Optional[str]) -> list[tuple[Optional[str], bytes]]:
    """Parses "kid=hex,kid2=hex" or bare "hex" entries (bare = legacy key without kid)."""
    out: list[tuple[Optional[str], bytes]] = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        kid, _, hex_key = item.rpartition("=")
        pk = bytes.fromhex(hex_key.strip())
        if len(pk) != 32:
            raise ValueError("Ed25519 public keys must be 32 bytes (64 hex chars).")
        out.append((_validate_kid(kid) if kid else None, pk))
    return out


# ----------------------------------------------------------------------
# High-Level Ed25519 Signer Class
# ----------------------------------------------------------------------
class Ed25519Signer:
    """Ed25519 asymmetric signer and verifier.

    Uses 'cryptography' package if available, otherwise RFC 8032 pure-python fallback.
    """

    def __init__(
        self,
        private_key_hex: Optional[str] = None,
        public_key_hex: Optional[str] = None,
        *,
        kid: Optional[str] = None,
        retired_public_keys: Optional[str] = None,
        force_pure_python: bool = False,
    ) -> None:
        if private_key_hex is None and public_key_hex is None:
            try:
                from app.config import get_settings
                settings = get_settings()
                private_key_hex = settings.ED25519_PRIVATE_KEY_HEX
                public_key_hex = settings.ED25519_PUBLIC_KEY_HEX
                kid = kid if kid is not None else settings.ED25519_KID
                if retired_public_keys is None:
                    retired_public_keys = settings.ED25519_RETIRED_PUBLIC_KEYS
            except Exception:
                pass
            if not private_key_hex:
                private_key_hex, public_key_hex = self.generate_keypair(force_pure_python=force_pure_python)

        self.private_key_bytes: Optional[bytes] = bytes.fromhex(private_key_hex) if private_key_hex else None
        self.public_key_bytes: Optional[bytes] = bytes.fromhex(public_key_hex) if public_key_hex else None

        # Check native library availability unless forced to pure Python
        self._has_crypto = False
        if not force_pure_python:
            try:
                from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
                self._has_crypto = True
            except ImportError:
                self._has_crypto = False

        # Derive public key if private is present and public is missing
        if self.private_key_bytes and not self.public_key_bytes:
            self.public_key_bytes = self._derive_public_key(self.private_key_bytes)

        # Key rotation: active kid (None = v1.0 tokens without kid) + retired verification keys.
        self.kid: Optional[str] = _validate_kid(kid) if kid else None
        self.retired_keys: list[tuple[Optional[str], bytes]] = parse_key_ring(retired_public_keys)

    def key_ring(self) -> list[tuple[Optional[str], bytes]]:
        """Active key first, then retired keys. Entries are (kid_or_None, raw_public_key)."""
        ring: list[tuple[Optional[str], bytes]] = []
        if self.public_key_bytes:
            ring.append((self.kid, self.public_key_bytes))
        ring.extend(self.retired_keys)
        return ring

    def public_keys(self) -> list[dict[str, Any]]:
        """Publishable key set (JWKS-like) for SDK key rings."""
        return [
            {"kid": k, "public_key_hex": pk.hex(), "status": "active" if i == 0 else "retired"}
            for i, (k, pk) in enumerate(self.key_ring())
        ]

    def stamp_kid(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Adds the active kid to a payload before signing (no-op when no kid is configured)."""
        if self.kid and "kid" not in payload:
            payload["kid"] = self.kid
        return payload

    @classmethod
    def generate_keypair(cls, *, force_pure_python: bool = False) -> tuple[str, str]:
        """Generates a new random Ed25519 keypair. Returns (private_hex, public_hex)."""
        raw_sk = os.urandom(32)
        if not force_pure_python:
            try:
                from cryptography.hazmat.primitives.asymmetric import ed25519
                pk_obj = ed25519.Ed25519PrivateKey.from_private_bytes(raw_sk)
                raw_pk = pk_obj.public_key().public_bytes_raw()
                return raw_sk.hex(), raw_pk.hex()
            except ImportError:
                pass
        raw_pk = _pure_publickey(raw_sk)
        return raw_sk.hex(), raw_pk.hex()

    def get_public_key_hex(self) -> str:
        """Returns the hex-encoded 32-byte Ed25519 public verification key."""
        return self.public_key_bytes.hex() if self.public_key_bytes else ""

    def _derive_public_key(self, sk_bytes: bytes) -> bytes:
        if self._has_crypto:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            return ed25519.Ed25519PrivateKey.from_private_bytes(sk_bytes).public_key().public_bytes_raw()
        return _pure_publickey(sk_bytes)

    def sign_bytes(self, data: bytes) -> bytes:
        """Signs raw byte data using private key."""
        if not self.private_key_bytes:
            raise ValueError("Private key is required to sign data.")
        if self._has_crypto:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            sk = ed25519.Ed25519PrivateKey.from_private_bytes(self.private_key_bytes)
            return sk.sign(data)
        assert self.public_key_bytes is not None
        return _pure_sign(data, self.private_key_bytes, self.public_key_bytes)

    def verify_bytes(self, sig: bytes, data: bytes, kid: Optional[str] = None) -> bool:
        """Verifies a signature against the key ring (matching kid first, then every key)."""
        ring = self.key_ring()
        if not ring:
            raise ValueError("Public key is required to verify signatures.")
        if kid is not None:
            ring.sort(key=lambda e: e[0] != kid)
        return any(self._verify_with(pk, sig, data) for _, pk in ring)

    def _verify_with(self, pk_bytes: bytes, sig: bytes, data: bytes) -> bool:
        if self._has_crypto:
            from cryptography.hazmat.primitives.asymmetric import ed25519
            try:
                ed25519.Ed25519PublicKey.from_public_bytes(pk_bytes).verify(sig, data)
                return True
            except Exception:
                return False
        return _pure_verify(sig, data, pk_bytes)

    def sign(self, payload: dict[str, Any]) -> str:
        """Signs canonical JSON dictionary payload and returns unpadded base64url signature."""
        canon_bytes = canonical_json_bytes(payload)
        sig_bytes = self.sign_bytes(canon_bytes)
        return b64url_encode(sig_bytes)

    def verify(self, payload: dict[str, Any], signature: str) -> bool:
        """Verifies unpadded base64url signature against canonical payload."""
        try:
            canon_bytes = canonical_json_bytes(payload)
            sig_bytes = b64url_decode(signature)
            kid = payload.get("kid")
            return self.verify_bytes(sig_bytes, canon_bytes, kid if isinstance(kid, str) else None)
        except Exception:
            return False

    def format_token(self, tier: str, payload: dict[str, Any], signature: str) -> str:
        """Formats full token: LIC-<TIER>-<BASE64URL_PAYLOAD>.<BASE64URL_SIGNATURE>."""
        canon_bytes = canonical_json_bytes(payload)
        payload_b64 = b64url_encode(canon_bytes)
        return f"LIC-{tier.upper()}-{payload_b64}.{signature}"

    def sign_token(self, payload: dict[str, Any]) -> str:
        """Computes signature and emits formatted license token."""
        tier = str(payload.get("tier", "community")).upper()
        payload = self.stamp_kid(dict(payload))
        sig_b64 = self.sign(payload)
        return self.format_token(tier, payload, sig_b64)

    def verify_token(
        self, token: str
    ) -> tuple[bool, Optional[dict[str, Any]], Optional[str]]:
        """Parses and validates a full license token string.

        Returns: (is_valid, payload_dict, error_code)
        """
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
        if not token_tier or not payload_b64:
            return False, None, "ERR_INVALID_TOKEN_FORMAT"

        try:
            payload_bytes = b64url_decode(payload_b64)
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return False, None, "ERR_MALFORMED_PAYLOAD"

        if not isinstance(payload, dict):
            return False, None, "ERR_INVALID_PAYLOAD_STRUCTURE"

        try:
            sig_bytes = b64url_decode(sig_b64)
            if len(sig_bytes) != 64:
                return False, payload, "ERR_INVALID_SIGNATURE"
            tok_kid = payload.get("kid")
            if not self.verify_bytes(sig_bytes, payload_bytes, tok_kid if isinstance(tok_kid, str) else None):
                return False, payload, "ERR_SIGNATURE_TAMPERED"
        except Exception:
            return False, payload, "ERR_INVALID_SIGNATURE"

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
