"""KeyFlint Billing Application Service.

Handles Stripe & LemonSqueezy webhook ingestion with constant-time HMAC verification,
replay protection idempotency, subscription lifecycles, and local webhook simulation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlencode
import uuid

import httpx

from app.application.dtos.billing_dtos import (
    BillingStatusResponse,
    CheckoutRequest,
    CheckoutResponse,
    CustomerLicenseSummary,
    CustomerPortalLookupRequest,
    CustomerPortalLookupResponse,
    PortalRequest,
    PortalResponse,
    WebhookSimulationRequest,
    WebhookSimulationResponse,
)
from app.application.dtos.license_dtos import (
    LicenseIssueRequest,
    LicenseRevokeRequest,
)
from app.application.dtos.quota_dtos import (
    QuotaReplenishRequest,
)
from app.application.services.license_service import LicenseService
from app.application.services.quota_service import QuotaService
from app.config import get_settings
from app.domain.entities.license import LicenseStatus, Tier
from app.domain.entities.webhook import WebhookRecord
from app.domain.exceptions import DomainError, LicenseNotFoundError
from app.domain.interfaces.customer_repository import ICustomerRepository
from app.domain.interfaces.email_sender import IEmailSender, LicenseEmailPayload
from app.domain.interfaces.license_repository import ILicenseRepository
from app.domain.interfaces.quota_repository import IQuotaRepository
from app.domain.interfaces.webhook_repository import IWebhookRepository

logger = logging.getLogger("keyflint.billing")

EMAIL_MAX_ATTEMPTS = 10
# Product names (Payment Link metadata / LemonSqueezy variant) -> entitlement tier.
_TIER_ALIASES: dict[str, Tier] = {
    "indie": Tier.INDIE,
    "agency": Tier.AGENCY,
    "pro": Tier.PRO,
    "managed": Tier.PRO,
    "studio": Tier.STUDIO,
    "lifetime": Tier.LIFETIME,
}


def _resolve_tier(raw: Optional[str]) -> Optional[Tier]:
    """Exact alias first, then a single keyword inside a product name ("Indie License"). None if unknown."""
    if not raw:
        return None
    norm = raw.strip().lower()
    if norm in _TIER_ALIASES:
        return _TIER_ALIASES[norm]
    hits = {tier for word, tier in _TIER_ALIASES.items() if re.search(rf"\b{word}\b", norm)}
    return hits.pop() if len(hits) == 1 else None


_PLACEHOLDER_EMAIL = re.compile(r"^buyer_[0-9a-f]{6}@acme\.ai$")


_TIER_UNIT_AMOUNTS_CENTS: dict[str, int] = {
    "community": 0,
    "indie": 14900,
    "agency": 34900,
    "pro": 2900,
    "studio": 8900,
    "lifetime": 19900,
}


class WebhookAuthenticationError(Exception):
    """Raised when webhook signature verification fails or timestamp is stale."""
    pass


class BillingService:
    """Orchestrates billing checkout sessions, webhooks, and local simulators."""

    def __init__(
        self,
        customer_repo: ICustomerRepository,
        license_repo: ILicenseRepository,
        quota_repo: IQuotaRepository,
        webhook_repo: IWebhookRepository,
        license_service: LicenseService,
        quota_service: QuotaService,
        stripe_webhook_secret: Optional[str] = None,
        lemonsqueezy_webhook_secret: Optional[str] = None,
        email_sender: Optional[IEmailSender] = None,
    ) -> None:
        self._customer_repo = customer_repo
        self._license_repo = license_repo
        self._quota_repo = quota_repo
        self._webhook_repo = webhook_repo
        self._license_service = license_service
        self._quota_service = quota_service
        self._email_sender = email_sender

        settings = get_settings()
        self._stripe_secret = stripe_webhook_secret or settings.STRIPE_WEBHOOK_SECRET
        self._lemonsqueezy_secret = (
            lemonsqueezy_webhook_secret or settings.LEMONSQUEEZY_WEBHOOK_SECRET
        )

    def create_checkout_session(self, request: CheckoutRequest) -> CheckoutResponse:
        """Creates a mock or live (Stripe / LemonSqueezy) checkout redirect session."""
        settings = get_settings()
        mode = settings.BILLING_MODE.strip().lower()
        provider = request.provider.strip().lower()

        if mode == "live":
            if provider == "lemonsqueezy":
                base_url = (settings.LEMONSQUEEZY_CHECKOUT_URL or "").strip()
                if not base_url:
                    raise DomainError(
                        "Live LemonSqueezy checkout requires LEMONSQUEEZY_CHECKOUT_URL.",
                        code="BILLING_PROVIDER_UNCONFIGURED",
                        status_code=503,
                    )
                sep = "&" if "?" in base_url else "?"
                query = urlencode(
                    {
                        "checkout[email]": request.customer_email,
                        "checkout[custom][tier]": request.tier,
                        "checkout[custom][customer_email]": request.customer_email,
                    }
                )
                session_id = f"ls_live_{uuid.uuid4().hex}"
                return CheckoutResponse(
                    checkout_url=f"{base_url}{sep}{query}",
                    session_id=session_id,
                    customer_email=request.customer_email,
                    tier=request.tier,
                    provider=provider,
                    mode="live",
                )

            stripe_key = (settings.STRIPE_SECRET_KEY or "").strip()
            if not stripe_key:
                raise DomainError(
                    "Live Stripe checkout requires STRIPE_SECRET_KEY.",
                    code="BILLING_PROVIDER_UNCONFIGURED",
                    status_code=503,
                )
            unit_amount = _TIER_UNIT_AMOUNTS_CENTS.get(request.tier, 1900)
            is_recurring = request.tier in ("pro", "studio")
            form_data: dict[str, str] = {
                "mode": "subscription" if is_recurring else "payment",
                "customer_email": request.customer_email,
                "success_url": settings.CHECKOUT_SUCCESS_URL,
                "cancel_url": settings.CHECKOUT_CANCEL_URL,
                "metadata[tier]": request.tier,
                "line_items[0][quantity]": "1",
                "line_items[0][price_data][currency]": "usd",
                "line_items[0][price_data][unit_amount]": str(unit_amount),
                "line_items[0][price_data][product_data][name]": f"KeyFlint {request.tier.upper()}",
            }
            if is_recurring:
                interval = "year" if (request.interval or "").lower() in ("yearly", "annual", "year") else "month"
                form_data["line_items[0][price_data][recurring][interval]"] = interval

            try:
                resp = httpx.post(
                    "https://api.stripe.com/v1/checkout/sessions",
                    auth=(stripe_key, ""),
                    data=form_data,
                    timeout=10.0,
                )
            except httpx.HTTPError as exc:
                raise DomainError(
                    f"Stripe checkout API request failed: {exc}",
                    code="BILLING_UPSTREAM_ERROR",
                    status_code=502,
                ) from exc

            if resp.status_code >= 400:
                raise DomainError(
                    f"Stripe rejected checkout session creation (HTTP {resp.status_code}).",
                    code="BILLING_UPSTREAM_ERROR",
                    status_code=502,
                )
            stripe_body = resp.json()
            return CheckoutResponse(
                checkout_url=str(stripe_body.get("url") or ""),
                session_id=str(stripe_body.get("id") or f"cs_live_{uuid.uuid4().hex}"),
                customer_email=request.customer_email,
                tier=request.tier,
                provider="stripe",
                mode="live",
            )

        session_id = f"cs_{provider}_{uuid.uuid4().hex}"
        checkout_url = f"/api/v1/billing/checkout/mock-session-{session_id}"
        return CheckoutResponse(
            checkout_url=checkout_url,
            session_id=session_id,
            customer_email=request.customer_email,
            tier=request.tier,
            provider=provider,
            mode="mock",
        )

    def create_portal_session(self, request: PortalRequest) -> PortalResponse:
        """Generates customer management portal session URL."""
        settings = get_settings()
        if settings.BILLING_MODE.strip().lower() == "live":
            stripe_key = (settings.STRIPE_SECRET_KEY or "").strip()
            if not stripe_key:
                raise DomainError(
                    "Live billing portal requires STRIPE_SECRET_KEY.",
                    code="BILLING_PROVIDER_UNCONFIGURED",
                    status_code=503,
                )
            try:
                cust_resp = httpx.get(
                    "https://api.stripe.com/v1/customers",
                    auth=(stripe_key, ""),
                    params={"email": request.customer_email, "limit": 1},
                    timeout=10.0,
                )
                if cust_resp.status_code >= 400:
                    raise DomainError(
                        "Unable to query customer from Stripe billing API.",
                        code="BILLING_UPSTREAM_ERROR",
                        status_code=502,
                    )
                customers = cust_resp.json().get("data") or []
                if not customers:
                    raise LicenseNotFoundError(
                        f"No Stripe billing profile found for '{request.customer_email}'."
                    )
                portal_resp = httpx.post(
                    "https://api.stripe.com/v1/billing_portal/sessions",
                    auth=(stripe_key, ""),
                    data={
                        "customer": str(customers[0]["id"]),
                        "return_url": settings.BILLING_PORTAL_RETURN_URL,
                    },
                    timeout=10.0,
                )
            except httpx.HTTPError as exc:
                raise DomainError(
                    f"Stripe billing portal API request failed: {exc}",
                    code="BILLING_UPSTREAM_ERROR",
                    status_code=502,
                ) from exc

            if portal_resp.status_code >= 400:
                raise DomainError(
                    f"Stripe rejected portal session creation (HTTP {portal_resp.status_code}).",
                    code="BILLING_UPSTREAM_ERROR",
                    status_code=502,
                )
            return PortalResponse(
                portal_url=str(portal_resp.json().get("url") or ""),
                customer_email=request.customer_email,
            )

        session_id = f"portal_{uuid.uuid4().hex}"
        portal_url = f"/api/v1/billing/portal/session-{session_id}"
        return PortalResponse(
            portal_url=portal_url,
            customer_email=request.customer_email,
        )

    def verify_stripe_signature(self, raw_body: bytes, signature_header: Optional[str]) -> None:
        """Verifies Stripe HMAC-SHA256 signature (supporting multi-v1 rotation) and timestamp tolerance."""
        if not signature_header:
            raise WebhookAuthenticationError("Missing Stripe-Signature header")

        timestamps: list[str] = []
        v1_signatures: list[str] = []
        for item in signature_header.split(","):
            if "=" not in item:
                continue
            k, val = item.strip().split("=", 1)
            if k == "t":
                timestamps.append(val)
            elif k == "v1" and val:
                v1_signatures.append(val)

        if not timestamps or not v1_signatures:
            raise WebhookAuthenticationError("Malformed Stripe-Signature header format")

        try:
            timestamp = int(timestamps[0])
        except ValueError:
            raise WebhookAuthenticationError("Invalid timestamp in Stripe-Signature")

        now = int(time.time())
        if abs(now - timestamp) > 300:
            raise WebhookAuthenticationError(f"Stale webhook timestamp (>300s): {timestamp} vs {now}")

        signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
        expected_sig = hmac.new(
            self._stripe_secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        if not any(hmac.compare_digest(expected_sig, cand) for cand in v1_signatures):
            raise WebhookAuthenticationError("Stripe webhook signature mismatch")

    def verify_lemonsqueezy_signature(self, raw_body: bytes, signature_header: Optional[str]) -> None:
        """Verifies LemonSqueezy X-Signature HMAC header."""
        if not signature_header:
            raise WebhookAuthenticationError("Missing X-Signature header")

        expected_sig = hmac.new(
            self._lemonsqueezy_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, signature_header.strip()):
            raise WebhookAuthenticationError("LemonSqueezy webhook signature mismatch")

    @staticmethod
    def _extract_webhook_context(
        body: dict[str, Any], raw_body: bytes
    ) -> tuple[str, str, Optional[str], Optional[Tier], Optional[str]]:
        """Normalizes payloads into (event_id, event_type, email, tier or None if unresolved, raw tier)."""
        meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
        data_node = body.get("data") if isinstance(body.get("data"), dict) else {}
        data_obj = data_node.get("object") if isinstance(data_node.get("object"), dict) else data_node
        attrs = data_node.get("attributes") if isinstance(data_node.get("attributes"), dict) else {}
        custom_data = meta.get("custom_data") if isinstance(meta.get("custom_data"), dict) else {}
        obj_meta = data_obj.get("metadata") if isinstance(data_obj.get("metadata"), dict) else {}
        cust_details = (
            data_obj.get("customer_details")
            if isinstance(data_obj.get("customer_details"), dict)
            else {}
        )

        raw_event_type = str(
            body.get("type")
            or meta.get("event_name")
            or body.get("event_name")
            or "unknown"
        )

        event_id_raw = (
            body.get("id")
            or meta.get("webhook_id")
            or (
                f"ls_{data_node.get('id')}_{raw_event_type}"
                if data_node.get("id") and meta.get("event_name")
                else None
            )
        )
        event_id = str(event_id_raw) if event_id_raw else f"evt_{hashlib.sha256(raw_body).hexdigest()[:24]}"

        email_raw = (
            data_obj.get("customer_email")
            or cust_details.get("email")
            or attrs.get("user_email")
            or attrs.get("customer_email")
            or custom_data.get("customer_email")
            or body.get("customer_email")
        )
        customer_email = str(email_raw).strip() if isinstance(email_raw, str) and email_raw.strip() else None

        tier_candidate = (
            obj_meta.get("tier")
            or custom_data.get("tier")
            or attrs.get("variant_name")
        )
        tier_raw = str(tier_candidate).strip() if tier_candidate else None
        if not tier_raw:
            # Metadata missing: infer only from an EXACT pre-tax, pre-discount USD list price.
            subtotal = data_obj.get("amount_subtotal")
            currency = str(data_obj.get("currency") or "").lower()
            by_price = {cents: name for name, cents in _TIER_UNIT_AMOUNTS_CENTS.items() if cents}
            if isinstance(subtotal, int) and currency == "usd" and subtotal in by_price:
                tier_raw = by_price[subtotal]
        return event_id, raw_event_type, customer_email, _resolve_tier(tier_raw), tier_raw

    # Stripe object reference prefixes used to link a payment back to its license.
    _PAYMENT_REF_FIELDS = ("payment_intent", "charge", "invoice", "subscription", "customer")
    _PAYMENT_REF_PREFIXES = ("pi_", "ch_", "in_", "sub_", "cus_", "cs_")

    @classmethod
    def _extract_payment_refs(cls, data_obj: dict[str, Any]) -> list[str]:
        """Collects Stripe IDs (session, payment_intent, charge, invoice, subscription, customer)."""
        refs: list[str] = []
        obj_id = data_obj.get("id")
        if isinstance(obj_id, str) and obj_id.startswith(cls._PAYMENT_REF_PREFIXES):
            refs.append(obj_id)
        for field_name in cls._PAYMENT_REF_FIELDS:
            val = data_obj.get(field_name)
            if isinstance(val, dict):
                val = val.get("id")
            if isinstance(val, str) and val.startswith(cls._PAYMENT_REF_PREFIXES) and val not in refs:
                refs.append(val)
        return refs

    def _flag_license(self, license_key: Optional[str], fields: dict[str, Any]) -> None:
        """Merges audit fields into license metadata."""
        lic = self._license_repo.get_by_key(license_key) if license_key else None
        if lic is not None:
            lic.metadata.update(fields)
            self._license_repo.save(lic)

    def _attach_payment_refs(self, license_key: Optional[str], refs: list[str]) -> None:
        """Stores payment references in license metadata so refunds/disputes can find it later."""
        if not license_key or not refs:
            return
        lic = self._license_repo.get_by_key(license_key)
        if lic is None:
            return
        existing = lic.metadata.get("payment_refs", [])
        if not isinstance(existing, list):
            existing = []
        merged = existing + [r for r in refs if r not in existing]
        if merged != existing:
            lic.metadata["payment_refs"] = merged[-50:]
            self._license_repo.save(lic)

    def _resolve_payment_licenses(self, data_obj: dict[str, Any]) -> tuple[list[Any], str]:
        """Finds licenses for a charge/dispute: specific refs first, then customer id, then email."""
        finder = getattr(self._license_repo, "find_by_payment_ref", None)
        refs = self._extract_payment_refs(data_obj)
        if finder is not None:
            # Most specific first: payment_intent/charge/invoice/subscription, customer last.
            for ref in sorted(refs, key=lambda r: r.startswith("cus_")):
                found = finder(ref)
                if found:
                    if ref.startswith("cus_") and len(found) > 1:
                        logger.error(
                            "Payment reversal matched %d licenses by customer %s only; none changed. "
                            "Revoke the right one by hand.", len(found), ref,
                        )
                        return [], "ambiguous_customer"
                    return found, ref
        billing = data_obj.get("billing_details") if isinstance(data_obj.get("billing_details"), dict) else {}
        email = billing.get("email") or data_obj.get("receipt_email")
        if isinstance(email, str) and email.strip():
            customer = self._customer_repo.get_by_email(email.strip())
            if customer:
                found = self._license_repo.list_by_customer_id(customer.id)
                if len(found) > 1:
                    logger.error(
                        "Payment reversal matched %d licenses by email only; none changed. "
                        "Revoke the right one by hand.", len(found),
                    )
                    return [], "ambiguous_email"
                return found, "email"
        return [], "none"

    _RECURRING_TIERS = (Tier.PRO, Tier.STUDIO)

    def _promotable_free_license(self, customer: Any) -> Optional[Any]:
        """A free Community license that was never billed: the only kind a purchase may upgrade in place."""
        for lic in self._license_repo.list_by_customer_id(customer.id):
            if (
                lic.tier == Tier.COMMUNITY
                and lic.status in (LicenseStatus.ACTIVE, LicenseStatus.GRACE_PERIOD, LicenseStatus.EXPIRED)
                and not self._license_service.is_revoked_id(lic.id)
                and not lic.metadata.get("payment_refs")
                and not lic.metadata.get("tier_unresolved")
            ):
                return lic
        return None

    def _resolve_subscription_licenses(self, data_obj: dict[str, Any], email: Optional[str]) -> list[Any]:
        """Licenses of one subscription: by its sub_ id, else the buyer's recurring-tier licenses only.

        Perpetual purchases (Indie, Agency, Lifetime) are never touched by subscription events.
        """
        sub_id = data_obj.get("subscription")
        if isinstance(sub_id, dict):
            sub_id = sub_id.get("id")
        if not sub_id and isinstance(data_obj.get("id"), str) and data_obj["id"].startswith("sub_"):
            sub_id = data_obj["id"]
        finder = getattr(self._license_repo, "find_by_payment_ref", None)
        if isinstance(sub_id, str) and sub_id and finder is not None:
            found = finder(sub_id)
            if found:
                return found
        if not email:
            return []
        customer = self._customer_repo.get_by_email(email)
        if not customer:
            return []
        return [
            lic for lic in self._license_repo.list_by_customer_id(customer.id) if lic.tier in self._RECURRING_TIERS
        ]

    def _handle_stripe_payment_reversal(self, event_type: str, data_obj: dict[str, Any]) -> dict[str, Any]:
        """charge.refunded / charge.dispute.* lifecycle. Returns outcome details."""
        licenses, matched_by = self._resolve_payment_licenses(data_obj)
        outcome: dict[str, Any] = {"matched_by": matched_by, "license_key": None, "license_status": None}

        if event_type == "charge.refunded":
            amount = int(data_obj.get("amount") or 0)
            refunded_amt = int(data_obj.get("amount_refunded") or 0)
            full = bool(data_obj.get("refunded")) or (amount > 0 and refunded_amt >= amount)
            if not full:
                outcome["action"] = "partial_refund_ignored"
                return outcome
            action, reason = "revoke", "payment_refunded"
        elif event_type == "charge.dispute.created":
            action, reason = "suspend", "payment_dispute"
        else:  # charge.dispute.closed
            dispute_status = str(data_obj.get("status") or "")
            if dispute_status == "lost":
                action, reason = "revoke", "payment_dispute_lost"
            elif dispute_status in ("won", "warning_closed"):
                action, reason = "reinstate", "payment_dispute_won"
            else:
                outcome["action"] = f"dispute_{dispute_status or 'unknown'}_ignored"
                return outcome

        outcome["action"] = action if licenses else "no_matching_license"
        for lic in licenses:
            already_revoked = lic.status == LicenseStatus.REVOKED or self._license_service.is_revoked_id(lic.id)
            if action == "revoke":
                if not already_revoked:
                    self._license_service.revoke(
                        LicenseRevokeRequest(license_key=lic.license_key, reason=reason)
                    )
                status = LicenseStatus.REVOKED
            elif already_revoked:
                status = LicenseStatus.REVOKED
            elif action == "suspend":
                if lic.status != LicenseStatus.SUSPENDED:
                    lic.suspend()
                    lic.metadata["suspension_reason"] = reason
                    self._license_repo.save(lic)
                status = lic.status
            else:  # reinstate only what a dispute suspended
                if lic.status == LicenseStatus.SUSPENDED and lic.metadata.get("suspension_reason") == "payment_dispute":
                    lic.reinstate()
                    lic.metadata.pop("suspension_reason", None)
                    self._license_repo.save(lic)
                status = lic.status
            outcome["license_key"] = lic.license_key
            outcome["license_status"] = status.value
        return outcome

    def deliver_license_email(self, license_key: str, recipient: Optional[str] = None) -> bool:
        """Emails the license and records the outcome in metadata.email_delivery (never raises)."""
        lic = self._license_repo.get_by_key(license_key)
        if lic is None:
            raise LicenseNotFoundError(license_key)
        to = recipient
        if not to:
            customer = self._customer_repo.get_by_id(lic.customer_id)
            to = customer.email if customer else None

        prev = lic.metadata.get("email_delivery") if isinstance(lic.metadata.get("email_delivery"), dict) else {}
        attempts = int(prev.get("attempts", 0)) + 1
        error: Optional[str] = None
        ok = False
        if self._email_sender is None:
            error = "email_sender_not_wired"
        elif not to or _PLACEHOLDER_EMAIL.match(to):
            error = "no_customer_email"
        else:
            try:
                ok = bool(
                    self._email_sender.send_license_issued(
                        LicenseEmailPayload(
                            recipient_email=to,
                            tier=lic.tier.value,
                            license_key=lic.license_key,
                            token=lic.license_key,
                            public_key_hex=self._license_service.get_public_key_hex(),
                            seats=lic.max_seats,
                            credits=lic.tier.default_allowance,
                            expires_at=lic.expires_at.isoformat() if lic.expires_at else None,
                        )
                    )
                )
                if not ok:
                    error = getattr(self._email_sender, "last_error", None) or "send_failed"
            except Exception as exc:  # provider bugs must never break provisioning
                error = f"exception: {exc}"

        lic.metadata["email_delivery"] = {
            "status": "sent" if ok else "failed",
            "attempts": attempts,
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
            "recipient": to,
            **({"error": error[:300]} if error else {}),
        }
        self._license_repo.save(lic)
        if ok:
            logger.info("License email delivered to %s (license %s, attempt %d)", to, lic.id, attempts)
        else:
            logger.error(
                "LICENSE EMAIL NOT DELIVERED to %s (license %s, attempt %d): %s",
                to,
                lic.id,
                attempts,
                error,
            )
        return ok

    def retry_failed_license_emails(self, max_attempts: int = EMAIL_MAX_ATTEMPTS) -> dict[str, int]:
        """Retries every license whose email_delivery.status is 'failed' (below max_attempts)."""
        finder = getattr(self._license_repo, "list_failed_email_deliveries", None)
        summary = {"retried": 0, "sent": 0, "failed": 0}
        if finder is None:
            return summary
        for lic in finder():
            info = lic.metadata.get("email_delivery") or {}
            if int(info.get("attempts", 0)) >= max_attempts or info.get("error") == "no_customer_email":
                continue
            if lic.status not in (LicenseStatus.ACTIVE, LicenseStatus.GRACE_PERIOD):
                continue
            summary["retried"] += 1
            if self.deliver_license_email(lic.license_key, recipient=info.get("recipient")):
                summary["sent"] += 1
            else:
                summary["failed"] += 1
        return summary

    def process_webhook(
        self,
        provider: str,
        raw_body: bytes,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Verifies and processes incoming webhook events idempotently."""
        provider = provider.strip().lower()
        lower_headers = {k.lower(): v for k, v in headers.items()}
        if provider == "stripe":
            self.verify_stripe_signature(raw_body, lower_headers.get("stripe-signature"))
        elif provider == "lemonsqueezy":
            self.verify_lemonsqueezy_signature(raw_body, lower_headers.get("x-signature"))
        else:
            raise ValueError(f"Unsupported payment provider: {provider}")

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            raise ValueError("Malformed JSON payload in webhook body")

        if not isinstance(body, dict):
            raise ValueError("Webhook body must be a JSON object")

        event_id, event_type, customer_email, target_tier, tier_raw = self._extract_webhook_context(body, raw_body)
        data_node = body.get("data") if isinstance(body.get("data"), dict) else {}
        data_obj = data_node.get("object") if isinstance(data_node.get("object"), dict) else {}
        reversal: Optional[dict[str, Any]] = None

        # 1. Idempotency Check (Deduplication)
        if self._webhook_repo.is_processed(event_id):
            return {
                "success": True,
                "already_processed": True,
                "event_id": event_id,
                "event_type": event_type,
                "status": "already_processed",
            }

        payload_hash = hashlib.sha256(raw_body).hexdigest()
        email_delivered: Optional[bool] = None
        unresolved_tier: Optional[str] = None
        license_key: Optional[str] = None
        license_status: Optional[str] = None

        # Normalize cross-provider lifecycle actions
        provision_events = {"checkout.session.completed", "order_created", "subscription_created"}
        renewal_events = {
            "invoice.payment_succeeded",
            "subscription_payment_success",
            "subscription_payment_recovered",
        }
        cancel_events = {
            "customer.subscription.deleted",
            "subscription_cancelled",
            "subscription_expired",
            "order_refunded",
        }
        failure_events = {"invoice.payment_failed", "subscription_payment_failed"}
        reversal_events = {"charge.refunded", "charge.dispute.created", "charge.dispute.closed"}

        # 2. Lifecycle Handling
        if event_type in provision_events:
            resolved_email = customer_email or f"buyer_{uuid.uuid4().hex[:6]}@acme.ai"
            customer = self._customer_repo.get_by_email(resolved_email)
            if target_tier is None:
                # Never grant a paid tier on a guess: issue COMMUNITY, flag it, leave existing licenses alone.
                logger.error(
                    "TIER UNRESOLVED for webhook %s (%s): metadata tier=%r. Issued COMMUNITY license for %s; "
                    "fix with POST /api/v1/licenses/issue + revoke, and set metadata.tier on the Payment Link.",
                    event_id,
                    event_type,
                    tier_raw,
                    resolved_email,
                )
                target_tier = Tier.COMMUNITY
                unresolved_tier = tier_raw or "missing"
                issue_resp = self._license_service.issue(
                    LicenseIssueRequest(customer_email=resolved_email, tier=target_tier.value)
                )
                license_key = issue_resp.license_key
                self._flag_license(license_key, {"tier_unresolved": unresolved_tier})
            else:
                # One license per purchase: a paid license is never merged into another. Only a free,
                # never-billed Community license is promoted, so the buyer keeps the key already in use.
                promotable = self._promotable_free_license(customer) if customer else None
                if promotable is not None:
                    upgraded = self._license_service.upgrade_existing(
                        license_entity=promotable,
                        target_tier=target_tier,
                        customer_email=customer.email,
                    )
                    self._quota_service.replenish(
                        QuotaReplenishRequest(
                            license_key=upgraded.license_key,
                            credits=target_tier.default_allowance,
                            reset_cycle=True,
                        )
                    )
                    license_key = upgraded.license_key
                else:
                    issue_resp = self._license_service.issue(
                        LicenseIssueRequest(
                            customer_email=resolved_email,
                            tier=target_tier.value,
                        )
                    )
                    license_key = issue_resp.license_key

            if tier_raw and license_key:
                self._flag_license(license_key, {"product": tier_raw.lower()})
            if provider == "stripe":
                self._attach_payment_refs(license_key, self._extract_payment_refs(data_obj))

            email_delivered: Optional[bool] = None
            if license_key:
                if customer_email is None:
                    logger.error(
                        "Webhook %s (%s) has no customer email; license issued but NOT emailed. "
                        "Resend with: keyflint resend-license <key> --to <email>",
                        event_id,
                        event_type,
                    )
                email_delivered = self.deliver_license_email(license_key, recipient=resolved_email)

        elif event_type in renewal_events and data_obj.get("billing_reason", "subscription_cycle") != "subscription_cycle":
            # One-time Payment Link invoices ("manual") and first subscription invoices are already
            # provisioned by checkout.session.completed; only a real cycle renews quota.
            logger.info("Ignoring %s with billing_reason=%r", event_type, data_obj.get("billing_reason"))

        elif event_type in renewal_events:
            if customer_email or data_obj:
                licenses = self._resolve_subscription_licenses(data_obj, customer_email)
                if licenses:
                    for lic in licenses:
                        if (
                            lic.status
                            not in (LicenseStatus.ACTIVE, LicenseStatus.GRACE_PERIOD)
                            or self._license_service.is_revoked_id(lic.id)
                        ):
                            continue
                        if lic.is_expired():
                            lic.extend_expiration(lic.tier.default_expires_in_days or 365)
                            lic.status = LicenseStatus.ACTIVE
                            self._license_repo.save(lic)
                        elif lic.status == LicenseStatus.GRACE_PERIOD:
                            lic.status = LicenseStatus.ACTIVE
                            self._license_repo.update_status(lic.id, LicenseStatus.ACTIVE)
                        replenish_resp = self._quota_service.replenish(
                            QuotaReplenishRequest(
                                license_key=lic.license_key,
                                credits=lic.tier.default_allowance,
                                reset_cycle=True,
                            )
                        )
                        license_key = lic.license_key
                        if provider == "stripe":
                            self._attach_payment_refs(lic.license_key, self._extract_payment_refs(data_obj))
                        if self._email_sender:
                            try:
                                self._email_sender.send_quota_replenished(
                                    recipient_email=customer_email,
                                    license_key=lic.license_key,
                                    added_credits=lic.tier.default_allowance,
                                    new_balance=replenish_resp.balance,
                                )
                            except Exception:
                                pass

        elif provider == "stripe" and event_type in reversal_events:
            reversal = self._handle_stripe_payment_reversal(event_type, data_obj)
            license_key = reversal["license_key"]
            license_status = reversal["license_status"]

        elif event_type in cancel_events:
            if customer_email or data_obj:
                licenses = self._resolve_subscription_licenses(data_obj, customer_email)
                if licenses:
                    for lic in licenses:
                        if lic.status != LicenseStatus.REVOKED:
                            self._license_service.revoke(
                                LicenseRevokeRequest(
                                    license_key=lic.license_key,
                                    reason="subscription_cancelled",
                                )
                            )
                            license_status = LicenseStatus.REVOKED.value

        elif event_type in failure_events:
            if customer_email or data_obj:
                licenses = self._resolve_subscription_licenses(data_obj, customer_email)
                if licenses:
                    for lic in licenses:
                        if lic.status not in (LicenseStatus.REVOKED, LicenseStatus.SUSPENDED):
                            self._license_repo.update_status(lic.id, LicenseStatus.GRACE_PERIOD)
                            license_status = LicenseStatus.GRACE_PERIOD.value

        if license_key and license_status is None:
            license_status = LicenseStatus.ACTIVE.value

        # 3. Record in Webhook Ledger
        self._webhook_repo.save(
            WebhookRecord(
                id=str(uuid.uuid4()),
                event_id=event_id,
                provider=provider,
                event_type=event_type,
                payload_hash=payload_hash,
                status="processed",
            )
        )

        return {
            "success": True,
            "processed": True,
            "event_id": event_id,
            "event_type": event_type,
            "license_key": license_key,
            "license_status": license_status,
            **({"email_delivered": email_delivered} if event_type in provision_events else {}),
            **({"tier_unresolved": unresolved_tier} if unresolved_tier else {}),
            **({"reversal": reversal} if reversal is not None else {}),
        }

    def simulate_webhook(self, request: WebhookSimulationRequest) -> WebhookSimulationResponse:
        """Generates and executes a cryptographically valid mock webhook event."""
        provider = request.provider.strip().lower()
        event_id = f"evt_sim_{uuid.uuid4().hex}"
        now = int(time.time())

        if provider == "lemonsqueezy":
            ls_event_map = {
                "checkout.session.completed": "order_created",
                "invoice.payment_succeeded": "subscription_payment_success",
                "customer.subscription.deleted": "subscription_cancelled",
                "invoice.payment_failed": "subscription_payment_failed",
            }
            ls_event_name = ls_event_map.get(request.event_type, request.event_type)
            event_payload: dict[str, Any] = {
                "meta": {
                    "event_name": ls_event_name,
                    "webhook_id": event_id,
                    "custom_data": {
                        "tier": request.tier,
                        "customer_email": request.customer_email,
                    },
                },
                "data": {
                    "id": f"ord_{uuid.uuid4().hex[:8]}",
                    "type": "orders",
                    "attributes": {
                        "user_email": request.customer_email,
                        "variant_name": request.tier,
                        "status": "paid",
                    },
                },
            }
        else:
            event_payload = {
                "id": event_id,
                "type": request.event_type,
                "created": now,
                "data": {
                    "object": {
                        "id": f"sub_{uuid.uuid4().hex[:8]}",
                        "customer_email": request.customer_email,
                        "metadata": {"tier": request.tier},
                        "payment_status": "paid",
                    }
                },
            }

        raw_body = json.dumps(event_payload, sort_keys=True).encode("utf-8")
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if provider == "stripe":
            signed_payload = f"{now}.".encode("utf-8") + raw_body
            sig = hmac.new(
                self._stripe_secret.encode("utf-8"),
                signed_payload,
                hashlib.sha256,
            ).hexdigest()
            headers["Stripe-Signature"] = f"t={now},v1={sig}"
        elif provider == "lemonsqueezy":
            sig = hmac.new(
                self._lemonsqueezy_secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).hexdigest()
            headers["X-Signature"] = sig
        else:
            raise ValueError(f"Unsupported payment provider '{request.provider}'")

        result = self.process_webhook(
            provider=provider,
            raw_body=raw_body,
            headers=headers,
        )

        return WebhookSimulationResponse(
            processed=True,
            event_id=event_id,
            event_type=request.event_type,
            customer_email=request.customer_email,
            tier=request.tier,
            license_key=result.get("license_key"),
            license_status=result.get("license_status"),
        )

    def get_billing_status(self, license_key: str) -> BillingStatusResponse:
        """Retrieves credit utilization, current tier, and billing status."""
        license_entity = self._license_repo.get_by_key(license_key)
        if license_entity is None:
            raise LicenseNotFoundError(f"License '{license_key}' not found.")

        effective_status = license_entity.status
        if self._license_service.is_revoked_id(license_entity.id):
            effective_status = LicenseStatus.REVOKED
        elif (
            effective_status
            not in (LicenseStatus.REVOKED, LicenseStatus.SUSPENDED, LicenseStatus.EXPIRED)
            and license_entity.is_expired(datetime.now(timezone.utc))
        ):
            self._license_repo.update_status(license_entity.id, LicenseStatus.EXPIRED)
            effective_status = LicenseStatus.EXPIRED

        customer = self._customer_repo.get_by_id(license_entity.customer_id)
        balance_info = self._quota_repo.get_balance(license_entity.id)

        return BillingStatusResponse(
            license_id=license_entity.id,
            license_key=license_entity.license_key,
            customer_email=customer.email if customer else None,
            tier=license_entity.tier.value,
            status=effective_status.value,
            credit_balance=balance_info.balance,
            total_allowance=balance_info.total_allowance,
            consumed=balance_info.consumed,
        )

    def lookup_customer_licenses(
        self, request: CustomerPortalLookupRequest
    ) -> CustomerPortalLookupResponse:
        """Returns customer license summaries, balances, and verification snippets."""
        q = request.query.strip()
        pub_key = self._license_service.get_public_key_hex()

        customer = None
        target_licenses = []

        if "@" in q:
            customer = self._customer_repo.get_by_email(q)
            if customer:
                target_licenses = self._license_repo.list_by_customer_id(customer.id)
        else:
            lic = self._license_repo.get_by_key(q)
            if lic:
                target_licenses = [lic]
                customer = self._customer_repo.get_by_id(lic.customer_id)

        if not target_licenses:
            raise LicenseNotFoundError(f"No licenses found matching query '{q}'.")

        resolved_email = customer.email if customer else "customer@external.ai"
        summaries: list[CustomerLicenseSummary] = []

        for lic in target_licenses:
            status = lic.status.value
            if self._license_service.is_revoked_id(lic.id):
                status = "revoked"
            elif lic.is_expired(datetime.now(timezone.utc)):
                status = "expired"

            balance_info = self._quota_repo.get_balance(lic.id)
            summaries.append(
                CustomerLicenseSummary(
                    license_id=lic.id,
                    license_key=lic.license_key,
                    tier=lic.tier.value,
                    status=status,
                    current_activations=lic.current_activations,
                    max_seats=lic.max_seats,
                    credit_balance=balance_info.balance,
                    total_allowance=balance_info.total_allowance,
                    expires_at=lic.expires_at.isoformat() if lic.expires_at else None,
                    created_at=lic.created_at.isoformat() if lic.created_at else "",
                )
            )

        first_token = summaries[0].license_key if summaries else "LIC-PRO-..."
        py_snip = (
            f"from keyflint_verify import verify_license\n\n"
            f'token = "{first_token}"\n'
            f'public_key = "{pub_key}"\n\n'
            f"payload = verify_license(token, public_key)\n"
            f'print(f"Valid: {{payload.is_valid}}, Tier: {{payload.tier}}")'
        )
        ts_snip = (
            f'import {{ verifyLicense }} from "keyflint-verify";\n\n'
            f'const token = "{first_token}";\n'
            f'const publicKey = "{pub_key}";\n\n'
            f"const res = await verifyLicense(token, publicKey);\n"
            f'console.log("Valid:", res.isValid, "Tier:", res.tier);'
        )

        return CustomerPortalLookupResponse(
            customer_email=resolved_email,
            public_key_hex=pub_key,
            total_licenses=len(summaries),
            licenses=summaries,
            python_snippet=py_snip,
            typescript_snippet=ts_snip,
        )
