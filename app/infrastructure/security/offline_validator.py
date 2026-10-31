"""KeyForge Standalone Offline Validator.

Zero external dependencies. Can be packaged and distributed independently.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from typing import Any, Optional

# RFC 8032 Curve Parameters for standalone zero-dependency verification
_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_D2 = (2 * _D) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)
_BY = (4 * pow(5, _Q - 2, _Q)) % _Q

_ExtPt = tuple[int, int, int, int]
_EXT_IDENTITY: _ExtPt = (0, 1, 1, 0)


def _xrec(y: int) -> int:
    u = (y * y - 1) % _Q
    v = (_D * y * y + 1) % _Q
    xx = (u * pow(v, _Q - 2, _Q)) % _Q
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * _I) % _Q
    if (x * x - xx) % _Q != 0:
        raise ValueError("Invalid Ed25519 point: no square root")
    if x & 1:
        x = _Q - x
    return x


_BX = _xrec(_BY)
_BP_EXT: _ExtPt = (_BX, _BY, 1, (_BX * _BY) % _Q)


def _ext_add(p1: _ExtPt, p2: _ExtPt) -> _ExtPt:
    x1, y1, z1, t1 = p1
    x2, y2, z2, t2 = p2
    a = ((y1 - x1) * (y2 - x2)) % _Q
    b = ((y1 + x1) * (y2 + x2)) % _Q
    c = (t1 * _D2 * t2) % _Q
    d = (2 * z1 * z2) % _Q
    e = (b - a) % _Q
    f = (d - c) % _Q
    g = (d + c) % _Q
    h = (b + a) % _Q
    return ((e * f) % _Q, (g * h) % _Q, (f * g) % _Q, (e * h) % _Q)


def _ext_dbl(p: _ExtPt) -> _ExtPt:
    x1, y1, z1, _ = p
    a = (x1 * x1) % _Q
    b = (y1 * y1) % _Q
    c = (2 * z1 * z1) % _Q
    h = (a + b) % _Q
    xy = x1 + y1
    e = (h - xy * xy) % _Q
    g = (a - b) % _Q
    f = (c + g) % _Q
    return ((e * f) % _Q, (g * h) % _Q, (f * g) % _Q, (e * h) % _Q)


def _smult_ext(pt: _ExtPt, e: int) -> _ExtPt:
    res = _EXT_IDENTITY
    addend = pt
    scalar = e
    while scalar > 0:
        if scalar & 1:
            res = _ext_add(res, addend)
        addend = _ext_dbl(addend)
        scalar >>= 1
    return res


def _dpt_ext(s: bytes) -> _ExtPt:
    if len(s) != 32:
        raise ValueError("Invalid point length")
    raw = int.from_bytes(s, "little")
    y = raw & ((1 << 255) - 1)
    sign_bit = (raw >> 255) & 1
    if y >= _Q:
        raise ValueError("Non-canonical y >= p")
    x = _xrec(y)
    if x == 0 and sign_bit == 1:
        raise ValueError("Invalid point: x=0 with sign bit 1")
    if (x & 1) != sign_bit:
        x = _Q - x
    if (-x * x + y * y - 1 - _D * x * x * y * y) % _Q != 0:
        raise ValueError("Point off Ed25519 curve")
    return (x, y, 1, (x * y) % _Q)


def _pure_ed25519_verify(sig: bytes, m: bytes, pk: bytes) -> bool:
    if len(sig) != 64 or len(pk) != 32:
        return False
    s_val = int.from_bytes(sig[32:], "little")
    if s_val >= _L:
        return False
    try:
        r_ext = _dpt_ext(sig[:32])
        a_ext = _dpt_ext(pk)
    except ValueError:
        return False
    h_val = int.from_bytes(hashlib.sha512(sig[:32] + pk + m).digest(), "little") % _L
    x1, y1, z1, _ = _smult_ext(_BP_EXT, s_val)
    x2, y2, z2, _ = _ext_add(r_ext, _smult_ext(a_ext, h_val))
    return (x1 * z2 - x2 * z1) % _Q == 0 and (y1 * z2 - y2 * z1) % _Q == 0


_B64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _b64url_decode(s: str) -> bytes:
    """Decode unpadded URL-safe base64 string to bytes with strict character set validation."""
    if not isinstance(s, str) or not _B64URL_PATTERN.match(s):
        raise ValueError("Invalid Base64URL string: contains illegal characters or whitespace.")
    pad_len = (4 - len(s) % 4) % 4
    return base64.b64decode((s + "=" * pad_len).encode("ascii"), altchars=b"-_", validate=True)


def validate_offline(
    license_token: Optional[str] = None,
    public_key_hex: str = "",
    current_time: Optional[int] = None,
    expected_machine_id: Optional[str] = None,
    *,
    license_key: Optional[str] = None,
    force_pure_python: bool = False,
) -> tuple[bool, Optional[dict[str, Any]], Optional[str]]:
    """Validates a KeyForge license token offline.

    Parameters:
        license_token: Complete token string (LIC-<TIER>-<PAYLOAD>.<SIG>)
        public_key_hex: 64-character hex string of 32-byte Ed25519 public key
        current_time: Optional Unix epoch seconds for expiration test (defaults to time.time())
        expected_machine_id: Optional local machine ID to enforce node-locking
        license_key: Alias for license_token
        force_pure_python: Force pure-stdlib RFC 8032 curve math even if cryptography is installed

    Returns:
        (is_valid: bool, payload: Optional[dict], error_code: Optional[str])
    """
    token = license_token if license_token is not None else license_key

    # 1. Structure validation
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

    # 2. Public key decode
    try:
        if not isinstance(public_key_hex, str):
            return False, None, "ERR_INVALID_PUBLIC_KEY"
        pub_bytes = bytes.fromhex(public_key_hex)
        if len(pub_bytes) != 32:
            return False, None, "ERR_INVALID_PUBLIC_KEY"
    except Exception:
        return False, None, "ERR_INVALID_PUBLIC_KEY"

    # 3. Base64url decodings
    try:
        payload_bytes = _b64url_decode(payload_b64)
    except Exception:
        return False, None, "ERR_MALFORMED_BASE64_PAYLOAD"

    try:
        sig_bytes = _b64url_decode(sig_b64)
        if len(sig_bytes) != 64:
            return False, None, "ERR_INVALID_SIGNATURE_LENGTH"
    except Exception:
        return False, None, "ERR_MALFORMED_BASE64_SIGNATURE"

    # 4. Cryptographic signature verification (OpenSSL fast path with pure-python RFC 8032 fallback)
    sig_valid = False
    if force_pure_python:
        sig_valid = _pure_ed25519_verify(sig_bytes, payload_bytes, pub_bytes)
    else:
        try:
            from cryptography.hazmat.primitives.asymmetric import ed25519

            c_pk = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
            c_pk.verify(sig_bytes, payload_bytes)
            sig_valid = True
        except ImportError:
            sig_valid = _pure_ed25519_verify(sig_bytes, payload_bytes, pub_bytes)
        except Exception:
            sig_valid = False

    if not sig_valid:
        return False, None, "ERR_SIGNATURE_TAMPERED"

    # 5. JSON payload deserialization
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return False, None, "ERR_MALFORMED_JSON_PAYLOAD"

    if not isinstance(payload, dict):
        return False, None, "ERR_INVALID_PAYLOAD_STRUCTURE"

    # 6. Tier consistency
    tier_val = payload.get("tier")
    if not isinstance(tier_val, str) or tier_val.lower() != token_tier.lower():
        return False, payload, "ERR_TIER_MISMATCH"

    # 7. Expiration boundary check
    now = current_time if current_time is not None else int(time.time())
    expires_at = payload.get("expires_at")
    if expires_at is not None:
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            return False, payload, "ERR_MALFORMED_EXPIRATION"
        if now > expires_at:
            return False, payload, "ERR_LICENSE_EXPIRED"

    # 8. Node lock / Machine ID enforcement
    locked_machine = payload.get("machine_id")
    if locked_machine is not None and not isinstance(locked_machine, str):
        return False, payload, "ERR_INVALID_PAYLOAD_STRUCTURE"

    if locked_machine is not None:
        if expected_machine_id is None or not isinstance(expected_machine_id, str):
            return False, payload, "ERR_NODE_LOCK_VIOLATION"
        if locked_machine.strip().lower() != expected_machine_id.strip().lower():
            return False, payload, "ERR_NODE_LOCK_VIOLATION"
    elif expected_machine_id is not None:
        return False, payload, "ERR_NODE_LOCK_VIOLATION"

    return True, payload, None
