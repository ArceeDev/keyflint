"""KeyForge licensing for MCP servers (FastMCP, MCPServer and the low-level ``mcp`` SDK).

    from keyforge_verify.mcp import KeyForge

    kf = KeyForge()                        # reads KEYFORGE_* environment variables

    @mcp.tool()
    @kf.require_license                    # offline Ed25519 check, no network
    def search(query: str) -> str: ...

    @mcp.tool()
    @kf.metered(credits=5)                 # offline check + POST /api/v1/quota/deduct
    async def summarize(url: str) -> str: ...

Put the KeyForge decorator *below* ``@mcp.tool()`` so the tool sees the wrapped function.
Both decorators work on sync and async functions and keep the original signature, so
the generated tool schema is unchanged.

Failures raise :class:`LicenseError`. When the ``mcp`` package is installed it subclasses
the SDK's standard MCP error (``MCPError`` in v2, ``McpError`` in v1), so the client
receives a JSON-RPC error with ``code``, ``message`` and ``data``. Without ``mcp`` it is a
plain ``Exception``.

Environment variables:
    KEYFORGE_LICENSE        license token (LIC-...)
    KEYFORGE_PUBLIC_KEYS    hex key, comma-separated keys, or kid=hex pairs
    KEYFORGE_URL            gateway base URL (required for @metered)
    KEYFORGE_MACHINE_ID     machine id for node-locked licenses (default: auto)
    KEYFORGE_DOMAIN         caller domain for domain-locked licenses
    KEYFORGE_CHECKOUT_URL   upgrade link shown when credits run out
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Mapping, Optional, Sequence, TypeVar, Union, cast

from . import PublicKeys, VerifyResult, decode_payload, verify_license
from .fingerprint import compute_machine_id

__all__ = [
    "KeyForge",
    "LicenseError",
    "LICENSE_INVALID",
    "FEATURE_NOT_ENTITLED",
    "QUOTA_EXHAUSTED",
    "GATEWAY_ERROR",
]

# JSON-RPC server error range (-32000..-32099), stable across SDKs.
LICENSE_INVALID = -32040
FEATURE_NOT_ENTITLED = -32041
QUOTA_EXHAUSTED = -32042
GATEWAY_ERROR = -32043

F = TypeVar("F", bound=Callable[..., Any])

try:  # mcp >= 2
    from mcp.shared.exceptions import MCPError as _MCPBase  # type: ignore[import-not-found]

    _MCP_FLAVOR = 2
except ImportError:  # pragma: no cover - depends on installed SDK
    try:  # mcp 1.x
        from mcp.shared.exceptions import McpError as _MCPBase  # type: ignore[import-not-found,no-redef]
        from mcp.types import ErrorData as _ErrorData  # type: ignore[import-not-found]

        _MCP_FLAVOR = 1
    except ImportError:
        _MCPBase = Exception  # type: ignore[misc,assignment]
        _MCP_FLAVOR = 0


class LicenseError(_MCPBase):  # type: ignore[misc,valid-type]
    """Standard MCP error carrying KeyForge details in ``data``.

    ``data["reason"]`` is the KeyForge error code (``ERR_LICENSE_EXPIRED``,
    ``QUOTA_EXHAUSTED``, ...). ``data["checkout_url"]`` is set when an upgrade link is configured.
    """

    def __init__(self, code: int, message: str, data: Mapping[str, Any]) -> None:
        payload = dict(data)
        self._text = message
        if _MCP_FLAVOR == 2:
            super().__init__(code, message, payload)
        elif _MCP_FLAVOR == 1:  # pragma: no cover
            super().__init__(_ErrorData(code=code, message=message, data=payload))
        else:
            super().__init__(message)
            self.code = code  # type: ignore[misc]
            self.message = message  # type: ignore[misc]
            self.data = payload  # type: ignore[misc]
        self.reason: str = str(payload.get("reason", ""))
        self.details: dict[str, Any] = payload

    def __str__(self) -> str:
        return self._text


def _error(code: int, reason: str, message: str, **extra: Any) -> LicenseError:
    data = {"reason": reason, **{k: v for k, v in extra.items() if v is not None}}
    return LicenseError(code, message, data)


def _parse_keys_env(raw: str) -> PublicKeys:
    items = [p.strip() for p in raw.split(",") if p.strip()]
    if items and all("=" in p for p in items):
        return {k.strip(): v.strip() for k, v in (p.split("=", 1) for p in items)}
    return items[0] if len(items) == 1 else items


class KeyForge:
    """Holds the license configuration and exposes the MCP decorators."""

    def __init__(
        self,
        *,
        license_key: Optional[str] = None,
        public_keys: Optional[PublicKeys] = None,
        gateway_url: Optional[str] = None,
        machine_id: Optional[str] = "auto",
        domain: Optional[str] = None,
        checkout_url: Optional[str] = None,
        timeout: float = 5.0,
        event_type: str = "mcp_tool_call",
    ) -> None:
        env = os.environ
        self.license_key = license_key or env.get("KEYFORGE_LICENSE", "")
        keys_env = env.get("KEYFORGE_PUBLIC_KEYS") or env.get("KEYFORGE_PUBLIC_KEY", "")
        self.public_keys: PublicKeys = public_keys if public_keys is not None else _parse_keys_env(keys_env)
        self.gateway_url = (gateway_url or env.get("KEYFORGE_URL", "")).rstrip("/")
        self.machine_id = env.get("KEYFORGE_MACHINE_ID", machine_id) if machine_id == "auto" else machine_id
        self.domain = domain or env.get("KEYFORGE_DOMAIN") or None
        self.checkout_url = checkout_url or env.get("KEYFORGE_CHECKOUT_URL") or None
        self.timeout = timeout
        self.event_type = event_type
        self._cached: Optional[VerifyResult] = None
        self._cached_until: float = 0.0

    # ------------------------------------------------------------------ offline

    def _resolved_machine_id(self) -> Optional[str]:
        if self.machine_id != "auto":
            return self.machine_id
        payload = decode_payload(self.license_key)
        locked = payload.get("machine_id") if isinstance(payload, dict) else None
        return compute_machine_id() if locked else None

    def check(self, features: Optional[Sequence[str]] = None) -> VerifyResult:
        """Verifies the configured license offline (cached until expiry, re-checked every 60 s)."""
        now = time.time()
        if self._cached is None or now >= self._cached_until:
            result = verify_license(
                self.license_key,
                self.public_keys,
                machine_id=self._resolved_machine_id(),
                domain=self.domain,
            )
            if not result.valid:
                raise _error(
                    LICENSE_INVALID,
                    result.error or "ERR_LICENSE_INVALID",
                    f"KeyForge license rejected: {result.error}.",
                    checkout_url=self.checkout_url,
                )
            exp = (result.payload or {}).get("expires_at")
            ttl = 60.0 if exp is None else max(0.0, min(60.0, float(exp) - now))
            self._cached, self._cached_until = result, now + ttl
        result = self._cached
        if features:
            have = set((result.payload or {}).get("features") or [])
            missing = [f for f in features if f not in have]
            if missing:
                raise _error(
                    FEATURE_NOT_ENTITLED,
                    "FEATURE_NOT_ENTITLED",
                    f"This tool requires the feature(s) {', '.join(missing)}, which your plan does not include.",
                    missing_features=missing,
                    tier=(result.payload or {}).get("tier"),
                    checkout_url=self.checkout_url,
                )
        return result

    # ------------------------------------------------------------------- online

    def deduct(
        self,
        credits: int = 1,
        *,
        idempotency_key: Optional[str] = None,
        event_type: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        """POST /api/v1/quota/deduct. Retries once on network errors with the same idempotency key."""
        if not self.gateway_url:
            raise _error(GATEWAY_ERROR, "GATEWAY_NOT_CONFIGURED", "KEYFORGE_URL is not set; metered tools need the gateway.")
        key = idempotency_key or f"mcp-{uuid.uuid4().hex}"
        body = {
            "license_key": self.license_key,
            "credits": int(credits),
            "idempotency_key": key,
            "event_type": event_type or self.event_type,
        }
        if metadata:
            body["metadata"] = dict(metadata)
        req = urllib.request.Request(
            f"{self.gateway_url}/api/v1/quota/deduct",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Idempotency-Key": key, "Accept": "application/json"},
            method="POST",
        )
        last_exc: Optional[Exception] = None
        for _attempt in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - configured URL
                    data = json.loads(resp.read().decode("utf-8") or "{}")
                    return cast("dict[str, Any]", data.get("data", data))
            except urllib.error.HTTPError as exc:
                raise self._http_error(exc.code, exc.read()) from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_exc = exc
        raise _error(GATEWAY_ERROR, "GATEWAY_UNREACHABLE", f"KeyForge gateway unreachable: {last_exc}.")

    def _http_error(self, status: int, raw: bytes) -> LicenseError:
        try:
            err = json.loads(raw.decode("utf-8")).get("error", {})
        except Exception:
            err = {}
        code = str(err.get("code") or f"HTTP_{status}")
        message = str(err.get("message") or f"Gateway returned HTTP {status}.")
        if status == 402 or code == "QUOTA_EXHAUSTED":
            text = "Credits exhausted for this license."
            if self.checkout_url:
                text += f" Upgrade or top up here: {self.checkout_url}"
            return _error(QUOTA_EXHAUSTED, "QUOTA_EXHAUSTED", text, status=402, checkout_url=self.checkout_url,
                          gateway_details=err.get("details") or None)
        if status in (401, 403, 404):
            return _error(LICENSE_INVALID, code, f"KeyForge license rejected: {message}", status=status,
                          checkout_url=self.checkout_url)
        return _error(GATEWAY_ERROR, code, f"KeyForge gateway error: {message}", status=status)

    # --------------------------------------------------------------- decorators

    def require_license(
        self, fn: Optional[F] = None, *, features: Optional[Sequence[str]] = None
    ) -> Union[F, Callable[[F], F]]:
        """Decorator: the tool runs only with a valid license (offline check)."""

        def decorate(func: F) -> F:
            return _wrap(func, lambda: self.check(features), None)

        return decorate(fn) if fn is not None else decorate

    def metered(
        self,
        credits: int = 1,
        *,
        features: Optional[Sequence[str]] = None,
        event_type: Optional[str] = None,
    ) -> Callable[[F], F]:
        """Decorator: offline license check, then debit ``credits`` before the tool runs."""
        if credits <= 0:
            raise ValueError("credits must be a positive integer")

        def decorate(func: F) -> F:
            name = event_type or f"mcp:{func.__name__}"
            return _wrap(
                func,
                lambda: self.check(features),
                lambda: self.deduct(credits, event_type=name),
            )

        return decorate


def _wrap(func: F, check: Callable[[], Any], charge: Optional[Callable[[], Any]]) -> F:
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            check()
            if charge is not None:
                await asyncio.to_thread(charge)
            return await func(*args, **kwargs)

        return cast(F, async_wrapper)

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        check()
        if charge is not None:
            charge()
        return func(*args, **kwargs)

    return cast(F, sync_wrapper)
