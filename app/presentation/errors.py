"""RFC 7807 Aligned Error Handling Envelopes for FastAPI."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.application.dtos.common import ErrorDetails, ErrorResponse, ResponseMetadata
from app.application.services.billing_service import WebhookAuthenticationError
from app.domain.exceptions import (
    CustomerNotFoundError,
    DomainError,
    DuplicateActivationError,
    IdempotencyConflictError,
    InvalidLicenseFormatError,
    InvalidSignatureError,
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseRevokedError,
    LicenseSuspendedError,
    NodeLockViolationError,
    QuotaExceededError,
    SeatLimitExceededError,
)
from app.presentation.middlewares import get_request_id

_HTTP_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    402: "QUOTA_EXHAUSTED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMIT_EXCEEDED",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


def create_error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Builds RFC 7807 aligned JSONResponse with synced request_id."""
    envelope = ErrorResponse(
        success=False,
        error=ErrorDetails(
            code=code,
            message=message,
            status_code=status_code,
            details=details or {},
        ),
        metadata=ResponseMetadata(
            request_id=get_request_id(request),
            timestamp=datetime.now(timezone.utc).isoformat(),
        ),
    )
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(),
        headers=dict(headers) if headers else None,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Registers domain and framework exception handlers on the FastAPI application."""

    @app.exception_handler(QuotaExceededError)
    async def quota_exceeded_handler(request: Request, exc: QuotaExceededError) -> JSONResponse:
        return create_error_response(
            status_code=402,
            code="QUOTA_EXHAUSTED",
            message=exc.message or "Token quota exhausted. Remaining balance: 0 credits.",
            details=exc.details,
            request=request,
        )

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict_handler(
        request: Request, exc: IdempotencyConflictError
    ) -> JSONResponse:
        return create_error_response(
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(SeatLimitExceededError)
    async def seat_limit_handler(request: Request, exc: SeatLimitExceededError) -> JSONResponse:
        return create_error_response(
            status_code=409,
            code="SEAT_LIMIT_EXCEEDED",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(DuplicateActivationError)
    async def duplicate_activation_handler(
        request: Request, exc: DuplicateActivationError
    ) -> JSONResponse:
        return create_error_response(
            status_code=409,
            code="DUPLICATE_ACTIVATION",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(LicenseNotFoundError)
    async def license_not_found_handler(
        request: Request, exc: LicenseNotFoundError
    ) -> JSONResponse:
        return create_error_response(
            status_code=404,
            code="LICENSE_NOT_FOUND",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(CustomerNotFoundError)
    async def customer_not_found_handler(
        request: Request, exc: CustomerNotFoundError
    ) -> JSONResponse:
        return create_error_response(
            status_code=404,
            code="CUSTOMER_NOT_FOUND",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(LicenseRevokedError)
    async def license_revoked_handler(request: Request, exc: LicenseRevokedError) -> JSONResponse:
        return create_error_response(
            status_code=403,
            code="LICENSE_REVOKED",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(LicenseSuspendedError)
    async def license_suspended_handler(
        request: Request, exc: LicenseSuspendedError
    ) -> JSONResponse:
        return create_error_response(
            status_code=403,
            code="LICENSE_SUSPENDED",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(LicenseExpiredError)
    async def license_expired_handler(request: Request, exc: LicenseExpiredError) -> JSONResponse:
        return create_error_response(
            status_code=403,
            code="LICENSE_EXPIRED",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(NodeLockViolationError)
    async def node_lock_handler(request: Request, exc: NodeLockViolationError) -> JSONResponse:
        return create_error_response(
            status_code=403,
            code="NODE_LOCK_VIOLATION",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(InvalidLicenseFormatError)
    async def invalid_format_handler(
        request: Request, exc: InvalidLicenseFormatError
    ) -> JSONResponse:
        return create_error_response(
            status_code=400,
            code="INVALID_LICENSE_FORMAT",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(InvalidSignatureError)
    async def invalid_signature_handler(
        request: Request, exc: InvalidSignatureError
    ) -> JSONResponse:
        return create_error_response(
            status_code=401,
            code="ERR_SIGNATURE_TAMPERED",
            message=exc.message,
            details=exc.details,
            request=request,
        )

    @app.exception_handler(WebhookAuthenticationError)
    async def webhook_auth_handler(
        request: Request, exc: WebhookAuthenticationError
    ) -> JSONResponse:
        return create_error_response(
            status_code=401,
            code="UNAUTHORIZED",
            message=str(exc),
            request=request,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        details = exc.detail if isinstance(exc.detail, dict) else None
        return create_error_response(
            status_code=exc.status_code,
            code=code,
            message=detail_msg,
            details=details,
            request=request,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        clean_errors = [
            {
                "type": err.get("type", "validation_error"),
                "loc": list(err.get("loc", ())),
                "msg": str(err.get("msg", "")),
            }
            for err in exc.errors()
        ]
        return create_error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request body or query parameter validation failed.",
            details={"errors": clean_errors},
            request=request,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        msg = str(exc)
        low = msg.lower()
        if "signature" in low or "stale" in low or "unauthorized" in low:
            return create_error_response(401, "UNAUTHORIZED", msg, request=request)
        if "malformed json" in low or "bad request" in low:
            return create_error_response(400, "BAD_REQUEST", msg, request=request)
        return create_error_response(422, "INVALID_VALUE", msg, request=request)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return create_error_response(
            status_code=getattr(exc, "status_code", 400),
            code=getattr(exc, "code", "DOMAIN_ERROR"),
            message=exc.message,
            details=exc.details,
            request=request,
        )
