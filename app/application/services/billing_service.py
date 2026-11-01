"""KeyForge Billing Application Service.

Handles Stripe & LemonSqueezy webhook ingestion with constant-time HMAC verification,
replay protection idempotency, subscription lifecycles, and local webhook simulation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
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


_TIER_UNIT_AMOUNTS_CENTS: dict[str, int] = {
    "community": 0,
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
            is_recurring = request.tier != "lifetime"
            form_data: dict[str, str] = {
                "mode": "subscription" if is_recurring else "payment",
                "customer_email": request.customer_email,
                "success_url": settings.CHECKOUT_SUCCESS_URL,
                "cancel_url": settings.CHECKOUT_CANCEL_URL,
                "metadata[tier]": request.tier,
                "line_items[0][quantity]": "1",
                "line_items[0][price_data][currency]": "usd",
                "line_items[0][price_data][unit_amount]": str(unit_amount),
                "line_items[0][price_data][product_data][name]": f"KeyForge {request.tier.upper()}",
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
    def _extract_webhook_context(body: dict[str, Any], raw_body: bytes) -> tuple[str, str, Optional[str], Tier]:
        """Normalizes Stripe and LemonSqueezy payloads into (event_id, raw_event_type, email, tier)."""
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
            or "pro"
        )
        tier_norm = str(tier_candidate).strip().lower()
        tier_aliases: dict[str, Tier] = {
            "indie": Tier.PRO,
            "agency": Tier.STUDIO,
        }
        if tier_norm in tier_aliases:
            tier_enum = tier_aliases[tier_norm]
        else:
            try:
                tier_enum = Tier(tier_norm)
            except ValueError:
                tier_enum = Tier.PRO

        return event_id, raw_event_type, customer_email, tier_enum

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

        event_id, event_type, customer_email, target_tier = self._extract_webhook_context(body, raw_body)

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

        # 2. Lifecycle Handling
        if event_type in provision_events:
            resolved_email = customer_email or f"buyer_{uuid.uuid4().hex[:6]}@acme.ai"
            customer = self._customer_repo.get_by_email(resolved_email)
            if customer:
                existing_licenses = self._license_repo.list_by_customer_id(customer.id)
                upgradable = [
                    lic
                    for lic in existing_licenses
                    if lic.status
                    in (
                        LicenseStatus.ACTIVE,
                        LicenseStatus.GRACE_PERIOD,
                        LicenseStatus.EXPIRED,
                    )
                    and not self._license_service.is_revoked_id(lic.id)
                ]
                upgradable.sort(
                    key=lambda item: 0
                    if item.status in (LicenseStatus.ACTIVE, LicenseStatus.GRACE_PERIOD)
                    else 1
                )
                if upgradable:
                    upgraded = self._license_service.upgrade_existing(
                        license_entity=upgradable[0],
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
            else:
                issue_resp = self._license_service.issue(
                    LicenseIssueRequest(
                        customer_email=resolved_email,
                        tier=target_tier.value,
                    )
                )
                license_key = issue_resp.license_key

            if self._email_sender and license_key:
                try:
                    pub_key = self._license_service.get_public_key_hex()
                    self._email_sender.send_license_issued(
                        LicenseEmailPayload(
                            recipient_email=resolved_email,
                            tier=target_tier.value,
                            license_key=license_key,
                            token=license_key,
                            public_key_hex=pub_key,
                            seats=target_tier.max_seats,
                            credits=target_tier.default_allowance,
                        )
                    )
                except Exception:
                    pass

        elif event_type in renewal_events:
            if customer_email:
                customer = self._customer_repo.get_by_email(customer_email)
                if customer:
                    licenses = self._license_repo.list_by_customer_id(customer.id)
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

        elif event_type in cancel_events:
            if customer_email:
                customer = self._customer_repo.get_by_email(customer_email)
                if customer:
                    licenses = self._license_repo.list_by_customer_id(customer.id)
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
            if customer_email:
                customer = self._customer_repo.get_by_email(customer_email)
                if customer:
                    licenses = self._license_repo.list_by_customer_id(customer.id)
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
            f"from keyforge_verify import verify_license\n\n"
            f'token = "{first_token}"\n'
            f'public_key = "{pub_key}"\n\n'
            f"payload = verify_license(token, public_key)\n"
            f'print(f"Valid: {{payload.is_valid}}, Tier: {{payload.tier}}")'
        )
        ts_snip = (
            f'import {{ verifyLicense }} from "keyforge-verify";\n\n'
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
