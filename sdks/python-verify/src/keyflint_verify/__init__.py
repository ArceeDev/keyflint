"""keyflint-verify: offline verification of KeyFlint license tokens.

``validate_offline`` is a verbatim copy of the KeyFlint gateway's
``app/infrastructure/security/offline_validator.py``. ``verify_license`` adds
key-ring support (single key, list of historical keys, or ``{kid: hex}``),
matching the ``keyflint-verify`` npm package.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Union

import time

from ._clock import ROLLBACK_LEEWAY_SECONDS, ClockGuard
from ._validator import validate_offline

__all__ = ["validate_offline", "verify_license", "decode_payload", "VerifyResult", "PublicKeys", "ClockGuard"]
__version__ = "1.1.0"

PublicKeys = Union[str, Sequence[str], Mapping[str, str]]


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    payload: Optional[dict[str, Any]]
    error: Optional[str]
    key_id: Optional[str] = None

    def __bool__(self) -> bool:
        return self.valid


def _normalize_keys(keys: PublicKeys) -> Optional[list[tuple[Optional[str], str]]]:
    if isinstance(keys, str):
        pairs: list[tuple[Optional[str], Any]] = [(None, keys)]
    elif isinstance(keys, Mapping):
        pairs = [(str(k), v) for k, v in keys.items()]
    elif isinstance(keys, Sequence):
        pairs = [(str(i), v) for i, v in enumerate(keys)]
    else:
        return None
    if not pairs:
        return None
    out: list[tuple[Optional[str], str]] = []
    for kid, hex_key in pairs:
        try:
            if not isinstance(hex_key, str) or len(bytes.fromhex(hex_key)) != 32:
                return None
        except ValueError:
            return None
        out.append((kid, hex_key))
    return out


def decode_payload(token: str) -> Optional[dict[str, Any]]:
    """Returns the token payload WITHOUT verifying it (display / routing only)."""
    try:
        payload_b64 = token.split(".")[0].split("-", 2)[2]
        raw = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


_PRE_SIGNATURE_ERRORS = frozenset({
    "ERR_EMPTY_TOKEN", "ERR_INVALID_TOKEN_FORMAT", "ERR_INVALID_TOKEN_PREFIX", "ERR_INVALID_PUBLIC_KEY",
    "ERR_MALFORMED_BASE64_PAYLOAD", "ERR_MALFORMED_BASE64_SIGNATURE", "ERR_INVALID_SIGNATURE_LENGTH",
})


def _peek_kid(token: str) -> Optional[str]:
    kid = (decode_payload(token) or {}).get("kid")
    return kid if isinstance(kid, str) else None


def verify_license(
    token: str,
    public_keys: PublicKeys,
    *,
    now: Optional[int] = None,
    machine_id: Optional[str] = None,
    domain: Optional[str] = None,
    force_pure_python: bool = False,
    last_seen: Optional[int] = None,
) -> VerifyResult:
    """Verifies a token against one or more trusted public keys.

    Tokens without ``kid`` (all KeyFlint v1.0 tokens) are tried against every key.
    With a ``{kid: hex}`` mapping, a token with a signed ``kid`` is checked only against
    that key (``ERR_UNKNOWN_KID`` when the mapping has no such kid). A single key or a
    list has no names, so every key is tried.

    ``last_seen`` (v1.2) is the latest Unix time this machine has observed (see
    :class:`ClockGuard`). A token with ``expires_at`` is rejected with
    ``ERR_CLOCK_ROLLBACK_DETECTED`` when the clock is more than 300 s behind it.
    """
    result = _verify_ring(token, public_keys, now=now, machine_id=machine_id, domain=domain,
                          force_pure_python=force_pure_python)
    if result.valid and last_seen is not None and (result.payload or {}).get("expires_at") is not None:
        current = now if now is not None else int(time.time())
        if current < last_seen - ROLLBACK_LEEWAY_SECONDS:
            return VerifyResult(False, result.payload, "ERR_CLOCK_ROLLBACK_DETECTED")
    return result


def _verify_ring(
    token: str,
    public_keys: PublicKeys,
    *,
    now: Optional[int],
    machine_id: Optional[str],
    domain: Optional[str],
    force_pure_python: bool,
) -> VerifyResult:
    ring = _normalize_keys(public_keys)
    if ring is None:
        # Structural token errors take precedence, exactly like validate_offline.
        _, _, err = validate_offline(token, "", now, machine_id, domain)
        return VerifyResult(False, None, err)

    kid = _peek_kid(token) if isinstance(token, str) else None
    if kid is not None and isinstance(public_keys, Mapping):
        matching = [e for e in ring if e[0] == kid]
        if not matching:
            # Report structural errors first (same order as the npm package), then the kid.
            _, _, err = validate_offline(token, ring[0][1], now, machine_id, domain,
                                         force_pure_python=force_pure_python)
            return VerifyResult(False, None, err if err in _PRE_SIGNATURE_ERRORS else "ERR_UNKNOWN_KID")
        ring = matching

    last = VerifyResult(False, None, "ERR_SIGNATURE_TAMPERED")
    for key_id, hex_key in ring:
        ok, payload, err = validate_offline(
            token, hex_key, now, machine_id, domain, force_pure_python=force_pure_python
        )
        if err == "ERR_SIGNATURE_TAMPERED":
            continue
        return VerifyResult(ok, payload, err, key_id if ok else None)
    return last
