"""keyforge-verify: offline verification of KeyForge license tokens.

``validate_offline`` is a verbatim copy of the KeyForge gateway's
``app/infrastructure/security/offline_validator.py``. ``verify_license`` adds
key-ring support (single key, list of historical keys, or ``{kid: hex}``),
matching the ``keyforge-verify`` npm package.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Union

from ._validator import validate_offline

__all__ = ["validate_offline", "verify_license", "VerifyResult", "PublicKeys"]
__version__ = "0.1.0"

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


def _peek_kid(token: str) -> Optional[str]:
    try:
        payload_b64 = token.split(".")[0].split("-", 2)[2]
        raw = base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
        kid = json.loads(raw).get("kid")
        return kid if isinstance(kid, str) else None
    except Exception:
        return None


def verify_license(
    token: str,
    public_keys: PublicKeys,
    *,
    now: Optional[int] = None,
    machine_id: Optional[str] = None,
    domain: Optional[str] = None,
    force_pure_python: bool = False,
) -> VerifyResult:
    """Verifies a token against one or more trusted public keys.

    Tokens without ``kid`` (all KeyForge v1.0 tokens) are tried against every key;
    tokens with a signed ``kid`` try the matching key first.
    """
    ring = _normalize_keys(public_keys)
    if ring is None:
        # Structural token errors take precedence, exactly like validate_offline.
        _, _, err = validate_offline(token, "", now, machine_id, domain)
        return VerifyResult(False, None, err)

    kid = _peek_kid(token) if isinstance(token, str) else None
    if kid is not None:
        ring.sort(key=lambda e: e[0] != kid)

    last = VerifyResult(False, None, "ERR_SIGNATURE_TAMPERED")
    for key_id, hex_key in ring:
        ok, payload, err = validate_offline(
            token, hex_key, now, machine_id, domain, force_pure_python=force_pure_python
        )
        if err == "ERR_SIGNATURE_TAMPERED":
            continue
        return VerifyResult(ok, payload, err, key_id if ok else None)
    return last
