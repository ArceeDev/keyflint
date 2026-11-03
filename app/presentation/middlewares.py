"""Application Middlewares: Security Headers, Payload Size Guards & Rate Limiting."""

from __future__ import annotations

from collections import OrderedDict, deque
from datetime import datetime, timezone
import functools
import ipaddress
import json
import logging
import math
import threading
import time
from typing import Any, Callable, Deque, MutableMapping, Optional
import uuid

from starlette.requests import Request

from app.application.dtos.common import ErrorDetails, ErrorResponse, ResponseMetadata
from app.config import get_settings

logger = logging.getLogger("keyflint.ratelimit")

ASGIApp = Callable[
    [
        MutableMapping[str, Any],
        Callable[[], Any],
        Callable[[MutableMapping[str, Any]], Any],
    ],
    Any,
]

MAX_PAYLOAD_BYTES: int = 64 * 1024  # Default 64 KB threshold

_STRICT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)


def _sanitize_request_id(raw: str | None) -> str:
    if raw:
        cleaned = "".join(ch for ch in raw.strip() if 32 < ord(ch) < 127)[:128]
        if cleaned:
            return cleaned
    return str(uuid.uuid4())


def get_request_id(request_or_scope: Request | MutableMapping[str, Any] | None) -> str:
    """Retrieves or initializes a request_id synced with scope['state']['request_id']."""
    if request_or_scope is None:
        return str(uuid.uuid4())

    if isinstance(request_or_scope, Request):
        scope = request_or_scope.scope
    else:
        scope = request_or_scope

    state = scope.setdefault("state", {})
    if isinstance(state, dict):
        existing = state.get("request_id")
        if existing:
            return str(existing)
        req_id = str(uuid.uuid4())
        state["request_id"] = req_id
        return req_id

    existing_attr = getattr(state, "request_id", None)
    if existing_attr:
        return str(existing_attr)
    req_id = str(uuid.uuid4())
    setattr(state, "request_id", req_id)
    return req_id


async def _send_json_error(
    send: Callable[[MutableMapping[str, Any]], Any],
    scope: MutableMapping[str, Any],
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    req_id = get_request_id(scope)
    envelope = ErrorResponse(
        success=False,
        error=ErrorDetails(
            code=code,
            message=message,
            status_code=status_code,
            details=details or {},
        ),
        metadata=ResponseMetadata(
            request_id=req_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )
    body = json.dumps(envelope.model_dump()).encode("utf-8")
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)

    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": headers,
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        }
    )


class _PayloadTooLargeSignal(BaseException):
    """Internal signal raised when streaming request body exceeds MAX_PAYLOAD_BYTES."""


class SecurityHeadersMiddleware:
    """Outermost ASGI middleware: assigns request_id and appends strict security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Any],
        send: Callable[[MutableMapping[str, Any]], Any],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        incoming_req_id: str | None = None
        for k, v in scope.get("headers", ()):
            if k.lower() == b"x-request-id":
                incoming_req_id = v.decode("latin-1", errors="ignore")
                break

        request_id = _sanitize_request_id(incoming_req_id)
        state = scope.setdefault("state", {})
        if isinstance(state, dict):
            state["request_id"] = request_id
        else:
            setattr(state, "request_id", request_id)

        path = str(scope.get("path") or "/")
        csp = _DOCS_CSP if path.startswith(("/docs", "/redoc", "/openapi.json")) else _STRICT_CSP

        async def send_with_security_headers(message: MutableMapping[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                raw_headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in raw_headers}

                security_pairs: list[tuple[bytes, bytes]] = [
                    (b"x-request-id", request_id.encode("ascii")),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (
                        b"strict-transport-security",
                        b"max-age=63072000; includeSubDomains; preload",
                    ),
                    (b"content-security-policy", csp.encode("ascii")),
                ]
                for key_bytes, val_bytes in security_pairs:
                    if key_bytes not in present:
                        raw_headers.append((key_bytes, val_bytes))
                message = dict(message)
                message["headers"] = raw_headers

            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class PayloadSizeLimitMiddleware:
    """Enforces maximum payload size via both Content-Length validation and streaming byte counter."""

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self._explicit_max_bytes = max_bytes

    def _effective_limit(self) -> int:
        if self._explicit_max_bytes is not None:
            return self._explicit_max_bytes
        return get_settings().MAX_PAYLOAD_BYTES

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Any],
        send: Callable[[MutableMapping[str, Any]], Any],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = self._effective_limit()

        parsed_lengths: set[int] = set()
        for k, v in scope.get("headers", ()):
            if k.lower() == b"content-length":
                raw_header = v.decode("latin-1", errors="ignore")
                parts = [p.strip() for p in raw_header.split(",")]
                if not parts or any(not p for p in parts):
                    await _send_json_error(
                        send,
                        scope,
                        status_code=400,
                        code="INVALID_CONTENT_LENGTH",
                        message="Malformed Content-Length header.",
                    )
                    return
                for raw_len in parts:
                    if not raw_len.isdigit():
                        await _send_json_error(
                            send,
                            scope,
                            status_code=400,
                            code="INVALID_CONTENT_LENGTH",
                            message="Malformed Content-Length header.",
                        )
                        return
                    parsed_lengths.add(int(raw_len))

        if len(parsed_lengths) > 1:
            await _send_json_error(
                send,
                scope,
                status_code=400,
                code="INVALID_CONTENT_LENGTH",
                message="Conflicting multiple Content-Length headers are not permitted.",
            )
            return

        if len(parsed_lengths) == 1:
            content_length = next(iter(parsed_lengths))
            if content_length > limit:
                await _send_json_error(
                    send,
                    scope,
                    status_code=413,
                    code="PAYLOAD_TOO_LARGE",
                    message=f"Payload size exceeds limit of {limit} bytes.",
                    details={"max_bytes": limit, "content_length": content_length},
                )
                return

        received_bytes = 0
        response_started = False

        async def guarded_receive() -> MutableMapping[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"") or b""
                received_bytes += len(chunk)
                if received_bytes > limit:
                    raise _PayloadTooLargeSignal()
            return message

        async def guarded_send(message: MutableMapping[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except _PayloadTooLargeSignal:
            if not response_started:
                await _send_json_error(
                    send,
                    scope,
                    status_code=413,
                    code="PAYLOAD_TOO_LARGE",
                    message=f"Streamed payload size exceeds limit of {limit} bytes.",
                    details={"max_bytes": limit},
                )


class SlidingWindowRateLimiter:
    """Thread-safe bounded in-memory sliding-window HTTP rate limiter."""

    def __init__(self, max_buckets: int = 10_000) -> None:
        self._lock = threading.Lock()
        self._buckets: OrderedDict[str, Deque[float]] = OrderedDict()
        self._max_buckets = max(64, max_buckets)
        self._last_sweep = time.monotonic()

    def _sweep_expired_locked(self, cutoff: float, now: float) -> None:
        stale_keys = [
            bucket_key
            for bucket_key, dq in self._buckets.items()
            if not dq or dq[-1] <= cutoff
        ]
        for bucket_key in stale_keys:
            self._buckets.pop(bucket_key, None)
        self._last_sweep = now

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: float,
    ) -> tuple[bool, int, int]:
        """Returns (allowed, remaining, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            if (now - self._last_sweep) >= max(5.0, window_seconds):
                self._sweep_expired_locked(cutoff, now)

            q = self._buckets.get(key)
            if q is not None:
                self._buckets.move_to_end(key)
            else:
                if len(self._buckets) >= self._max_buckets:
                    self._sweep_expired_locked(cutoff, now)
                    while len(self._buckets) >= self._max_buckets:
                        self._buckets.popitem(last=False)
                q = deque()
                self._buckets[key] = q

            while q and q[0] <= cutoff:
                q.popleft()

            if len(q) >= limit:
                oldest = q[0]
                retry_after = max(1, int(math.ceil((oldest + window_seconds) - now)))
                return False, 0, retry_after

            q.append(now)
            remaining = max(0, limit - len(q))
            return True, remaining, 0

    def reset(self) -> None:
        """Clears all rate-limit buckets (used for deterministic test isolation)."""
        with self._lock:
            self._buckets.clear()


rate_limiter = SlidingWindowRateLimiter()

_EXEMPT_PREFIXES = (
    "/healthz",
    "/readyz",
    "/api/v1/health",
    "/static",
    "/docs",
    "/redoc",
    "/openapi.json",
)


_PROXY_HEADERS = (b"x-forwarded-for", b"x-real-ip", b"fly-client-ip", b"cf-connecting-ip")
_proxy_warning_logged = [False]
_DEFAULT_TRUSTED = "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"


@functools.lru_cache(maxsize=8)
def _trusted_networks(raw: str) -> tuple[Any, ...]:
    nets = []
    for item in (raw.strip() or _DEFAULT_TRUSTED).split(","):
        item = item.strip()
        if item:
            nets.append(ipaddress.ip_network(item, strict=False))
    return tuple(nets)


def _ip_in(value: str, nets: tuple[Any, ...]) -> bool:
    try:
        ip = ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return False
    return any(ip.version == n.version and ip in n for n in nets)


class RateLimitMiddleware:
    """Applies sliding-window HTTP rate limits prior to route execution or quota deduction."""

    def __init__(
        self,
        app: ASGIApp,
        limiter: SlidingWindowRateLimiter = rate_limiter,
    ) -> None:
        self.app = app
        self._limiter = limiter

    @staticmethod
    def _extract_client_ip(
        scope: MutableMapping[str, Any],
        trust_proxy_headers: bool = False,
        mode: Optional[str] = None,
        trusted_proxies: str = "",
    ) -> str:
        """Client IP for rate limiting, per TRUSTED_PROXY_MODE (see app/config.py).

        The client controls every header it sends, so a header is only believed when the
        configured proxy is the one that sets it (and, where possible, the TCP peer is that proxy).
        """
        mode = mode or ("fly" if trust_proxy_headers else "direct")
        client = scope.get("client")
        peer = str(client[0])[:128] if client and len(client) >= 1 and client[0] else "local"
        headers: dict[bytes, str] = {}
        for k, v in scope.get("headers", ()):
            headers.setdefault(k.lower(), v.decode("latin-1", errors="ignore").strip())

        if mode == "direct":
            if not _proxy_warning_logged[0] and any(h in headers for h in _PROXY_HEADERS):
                _proxy_warning_logged[0] = True
                logger.warning(
                    "Proxy headers seen but TRUSTED_PROXY_MODE=direct: rate limits use the proxy's IP, "
                    "so all clients share one bucket. Set TRUSTED_PROXY_MODE (fly|cloudflare|standard)."
                )
            return peer

        if mode == "fly":
            # Fly's edge sets Fly-Client-IP, else the right-most X-Forwarded-For hop (appended by it).
            if headers.get(b"fly-client-ip"):
                return headers[b"fly-client-ip"][:128]
            hops = [h.strip() for h in headers.get(b"x-forwarded-for", "").split(",") if h.strip()]
            return hops[-1][:128] if hops else peer

        nets = _trusted_networks(trusted_proxies)
        if not _ip_in(peer, nets):
            return peer  # request did not come through our proxy: ignore its headers
        if mode == "cloudflare":
            return (headers.get(b"cf-connecting-ip") or peer)[:128]
        # standard: walk X-Forwarded-For from the right, skipping our own proxies.
        hops = [h.strip() for h in headers.get(b"x-forwarded-for", "").split(",") if h.strip()]
        for hop in reversed(hops):
            if not _ip_in(hop, nets):
                return hop[:128]
        if hops:
            return hops[0][:128]
        return (headers.get(b"x-real-ip") or peer)[:128]

    async def __call__(
        self,
        scope: MutableMapping[str, Any],
        receive: Callable[[], Any],
        send: Callable[[MutableMapping[str, Any]], Any],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "/")
        if path == "/" or path.startswith(_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        settings = get_settings()
        if not settings.RATE_LIMIT_ENABLED:
            await self.app(scope, receive, send)
            return

        is_webhook = path.startswith("/api/v1/webhooks/")
        limit = (
            settings.RATE_LIMIT_WEBHOOK_REQUESTS
            if is_webhook
            else settings.RATE_LIMIT_REQUESTS
        )
        window = max(1.0, float(settings.RATE_LIMIT_WINDOW_SECONDS))
        bucket_ns = "webhook" if is_webhook else "api"
        client_ip = self._extract_client_ip(
            scope,
            mode=settings.proxy_mode,
            trusted_proxies=settings.TRUSTED_PROXY_IPS,
        )
        allowed, remaining, retry_after = self._limiter.check(
            f"{bucket_ns}:{client_ip}",
            limit=limit,
            window_seconds=window,
        )

        if not allowed:
            await _send_json_error(
                send,
                scope,
                status_code=429,
                code="RATE_LIMIT_EXCEEDED",
                message=f"Rate limit exceeded ({limit} requests per {int(window)}s).",
                details={"limit": limit, "window_seconds": int(window), "retry_after": retry_after},
                extra_headers=[
                    (b"retry-after", str(retry_after).encode("ascii")),
                    (b"x-ratelimit-limit", str(limit).encode("ascii")),
                    (b"x-ratelimit-remaining", b"0"),
                ],
            )
            return

        async def send_with_ratelimit_headers(message: MutableMapping[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                raw_headers = list(message.get("headers", []))
                raw_headers.append((b"x-ratelimit-limit", str(limit).encode("ascii")))
                raw_headers.append((b"x-ratelimit-remaining", str(remaining).encode("ascii")))
                message = dict(message)
                message["headers"] = raw_headers
            await send(message)

        await self.app(scope, receive, send_with_ratelimit_headers)
