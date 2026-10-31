"""KeyForge Billing Application Service.

Handles Stripe & LemonSqueezy webhook ingestion with constant-time HMAC verification,
replay protection idempotency, subscription lifecycles, and local webhook simulation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Optional

from app.application.dtos.billing_dtos import (
    BillingStatusResponse,
    CheckoutRequest,
    CheckoutResponse,
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
    QuotaBalanceRequest,
    QuotaReplenishRequest,
)
from app.application.services.license_service import LicenseService
from app.application.services.quota_service import QuotaService
from app.config import get_settings
from app.domain.entities.license import License, LicenseStatus, Tier
from app.domain.entities.webhook import WebhookRecord
from app.domain.exceptions import LicenseNotFoundError
from app.domain.interfaces.customer_repository import ICustomerRepository
from app.domain.interfaces.license_repository import ILicenseRepository
from app.domain.interfaces.quota_repository import IQuotaRepository
from app.domain.interfaces.webhook_repository import IWebhookRepository


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
    ) -> None:
        self._customer_repo = customer_repo
        self._license_repo = license_repo
        self._quota_repo = quota_repo
        self._webhook_repo = webhook_repo
        self._license_service = license_service
        self._quota_service = quota_service

        settings = get_settings()
        self._stripe_secret = stripe_webhook_secret or settings.STRIPE_WEBHOOK_SECRET
        self._lemonsqueezy_secret = (
            lemonsqueezy_webhook_secret or settings.LEMONSQUEEZY_WEBHOOK_SECRET
        )

    def create_checkout_session(self, request: CheckoutRequest) -> CheckoutResponse:
        """Creates a mock or Stripe checkout redirect session."""
        session_id = f"cs_{uuid.uuid4().hex}"
        checkout_url = f"/api/v1/billing/checkout/mock-session-{session_id}"
        return CheckoutResponse(
            checkout_url=checkout_url,
            session_id=session_id,
            customer_email=request.customer_email,
            tier=request.tier,
        )

    def create_portal_session(self, request: PortalRequest) -> PortalResponse:
        """Generates customer management portal session URL."""
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
                    lic for lic in existing_licenses if lic.status != LicenseStatus.REVOKED
                ]
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

        elif event_type in renewal_events:
            if customer_email:
                customer = self._customer_repo.get_by_email(customer_email)
                if customer:
                    licenses = self._license_repo.list_by_customer_id(customer.id)
                    for lic in licenses:
                        if lic.status == LicenseStatus.REVOKED:
                            continue
                        if lic.status in (
                            LicenseStatus.GRACE_PERIOD,
                            LicenseStatus.SUSPENDED,
                            LicenseStatus.EXPIRED,
                        ):
                            if lic.is_expired():
                                lic.extend_expiration(lic.tier.default_expires_in_days or 365)
                                self._license_repo.save(lic)
                            else:
                                self._license_repo.update_status(lic.id, LicenseStatus.ACTIVE)
                        self._quota_service.replenish(
                            QuotaReplenishRequest(
                                license_key=lic.license_key,
                                credits=lic.tier.default_allowance,
                                reset_cycle=True,
                            )
                        )
                        license_key = lic.license_key

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

        customer = self._customer_repo.get_by_id(license_entity.customer_id)
        balance_info = self._quota_repo.get_balance(license_entity.id)

        return BillingStatusResponse(
            license_id=license_entity.id,
            license_key=license_entity.license_key,
            customer_email=customer.email if customer else None,
            tier=license_entity.tier.value,
            status=license_entity.status.value,
            credit_balance=balance_info.balance,
            total_allowance=balance_info.total_allowance,
            consumed=balance_info.consumed,
        )
