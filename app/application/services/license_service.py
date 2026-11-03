"""KeyFlint License Application Service.

File: app/application/services/license_service.py
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.application.dtos.license_dtos import (
    LicenseActivateRequest,
    LicenseActivateResponse,
    LicenseIssueRequest,
    LicenseIssueResponse,
    LicenseRevokeRequest,
    LicenseRevokeResponse,
    LicenseVerifyRequest,
    LicenseVerifyResponse,
)
from app.config import get_settings
from app.domain.entities.customer import Customer
from app.domain.entities.license import (
    License,
    LicenseStatus,
    Tier,
    matches_allowed_domains,
    normalize_domain_host,
)
from app.domain.entities.quota import QuotaLedger
from app.domain.exceptions import (
    LicenseExpiredError,
    LicenseNotFoundError,
    LicenseRevokedError,
    LicenseSuspendedError,
    NodeLockViolationError,
)
from app.domain.interfaces.crypto_signer import ICryptoSigner
from app.domain.interfaces.customer_repository import ICustomerRepository
from app.domain.interfaces.license_repository import ILicenseRepository
from app.domain.interfaces.quota_repository import IQuotaRepository
from app.infrastructure.security.ed25519_signer import Ed25519Signer
from app.infrastructure.security.hmac_signer import HmacSha256Signer


class LicenseService:
    """Orchestrates license lifecycle use cases: issuance, verification, activation, revocation."""

    def __init__(
        self,
        license_repo: ILicenseRepository,
        customer_repo: ICustomerRepository,
        quota_repo: IQuotaRepository,
        signer: Optional[ICryptoSigner] = None,
        hmac_signer: Optional[ICryptoSigner] = None,
        conn: Optional[Any] = None,
    ) -> None:
        self._license_repo = license_repo
        self._customer_repo = customer_repo
        self._quota_repo = quota_repo
        self._conn = (
            conn
            or getattr(license_repo, "_conn", None)
            or getattr(customer_repo, "_conn", None)
            or getattr(quota_repo, "_conn", None)
        )

        settings = get_settings()
        self._signer = signer or Ed25519Signer(
            private_key_hex=settings.ED25519_PRIVATE_KEY_HEX,
            public_key_hex=settings.ED25519_PUBLIC_KEY_HEX,
            kid=settings.ED25519_KID,
            retired_public_keys=settings.ED25519_RETIRED_PUBLIC_KEYS,
        )
        self._hmac_signer = hmac_signer or HmacSha256Signer(
            secret_key=settings.SECRET_KEY
        )

    def issue(self, request: LicenseIssueRequest) -> LicenseIssueResponse:
        """Issues a cryptographically signed license key, creates customer if absent,

        and provisions the initial token-bucket quota allowance atomically.
        """
        # 1. Resolve or prepare customer entity
        customer = self._customer_repo.get_by_email(request.customer_email)
        now = datetime.now(timezone.utc)
        is_new_customer = False
        if customer is None:
            is_new_customer = True
            customer = Customer(
                id=str(uuid.uuid4()),
                email=request.customer_email,
                company=request.company,
                created_at=now,
                updated_at=now,
            )

        # 2. Determine tier and canonical entitlements
        tier_enum = Tier(request.tier.lower())
        effective_seats = request.get_effective_max_seats()
        max_seats = (
            effective_seats
            if effective_seats is not None
            else tier_enum.default_max_activations
        )
        if max_seats <= 0:
            raise ValueError("max_seats must be a positive integer.")

        quota_credits = tier_enum.default_allowance
        features = list(request.features) if request.features is not None else list(tier_enum.default_features)

        days = (
            request.expires_in_days
            if request.expires_in_days is not None
            else tier_enum.default_expires_in_days
        )
        expires_at = (now + timedelta(days=days)) if days is not None else None

        license_id = str(uuid.uuid4())
        nonce = secrets.token_hex(8)

        # Optional hardware / domain bindings
        lic_metadata: dict[str, Any] = dict(request.metadata or {})
        machine_id_norm: Optional[str] = None
        if request.machine_id and request.machine_id.strip():
            machine_id_norm = request.machine_id.strip().lower()
            lic_metadata["machine_id"] = machine_id_norm

        domains_norm: Optional[list[str]] = None
        if request.allowed_domains:
            cleaned: list[str] = []
            for raw_dom in request.allowed_domains:
                if raw_dom and raw_dom.strip():
                    norm_dom = normalize_domain_host(raw_dom, allow_wildcard=True)
                    if norm_dom is None:
                        raise ValueError(f"Invalid allowed_domains pattern: {raw_dom!r}")
                    cleaned.append(norm_dom)
            if cleaned:
                domains_norm = cleaned
                lic_metadata["allowed_domains"] = cleaned

        # 3. Build canonical payload for cryptographic signing
        payload: dict[str, Any] = {
            "customer_email": customer.email,
            "customer_id": customer.id,
            "expires_at": int(expires_at.timestamp()) if expires_at else None,
            "features": features,
            "issued_at": int(now.timestamp()),
            "license_id": license_id,
            "max_seats": max_seats,
            "nonce": nonce,
            "tier": tier_enum.value,
        }
        if machine_id_norm is not None:
            payload["machine_id"] = machine_id_norm
        if domains_norm is not None:
            payload["allowed_domains"] = domains_norm

        # 4. Select signer based on algorithm requested
        algo = (request.signing_algorithm or "ed25519").lower()
        active_signer = self._hmac_signer if ("hmac" in algo) else self._signer

        if active_signer is self._signer and hasattr(active_signer, "stamp_kid"):
            active_signer.stamp_kid(payload)

        # 5. Sign payload and format token (performed in-memory BEFORE taking DB write lock)
        signature = active_signer.sign(payload)
        license_key = active_signer.format_token(tier_enum.value, payload, signature)

        # 6. Build license entity
        license_entity = License(
            id=license_id,
            customer_id=customer.id,
            license_key=license_key,
            tier=tier_enum,
            status=LicenseStatus.ACTIVE,
            max_seats=max_seats,
            current_activations=0,
            expires_at=expires_at,
            created_at=now,
            signature=signature,
            features=tuple(features),
            metadata=lic_metadata,
        )

        # 7. Build quota ledger entity
        quota_ledger = QuotaLedger(
            id=str(uuid.uuid4()),
            license_id=license_id,
            total_allowance=quota_credits,
            balance=quota_credits,
            consumed=0,
            last_reset_at=now,
            updated_at=now,
        )

        # 8. Atomic multi-entity persistence
        if self._conn is not None:
            from app.infrastructure.database.connection import transaction
            with transaction(self._conn):
                if is_new_customer:
                    self._customer_repo.save(customer)
                self._license_repo.save(license_entity)
                self._quota_repo.save(quota_ledger)
        else:
            if is_new_customer:
                self._customer_repo.save(customer)
            self._license_repo.save(license_entity)
            self._quota_repo.save(quota_ledger)

        return LicenseIssueResponse(
            license_id=license_id,
            license_key=license_key,
            customer_id=customer.id,
            customer_email=customer.email,
            tier=tier_enum.value,
            max_seats=max_seats,
            max_activations=max_seats,
            expires_at=expires_at,
            signature=signature,
            quota_credits=quota_credits,
        )

    def upgrade_existing(
        self,
        license_entity: License,
        target_tier: Tier,
        customer_email: str,
    ) -> License:
        """Upgrades an existing non-revoked, non-suspended license to a new tier and re-signs its token."""
        if license_entity.status == LicenseStatus.REVOKED or self.is_revoked_id(license_entity.id):
            raise LicenseRevokedError("Cannot upgrade a revoked license.")
        if license_entity.status == LicenseStatus.SUSPENDED:
            raise LicenseSuspendedError("Cannot upgrade a suspended license.")

        now = datetime.now(timezone.utc)
        old_key = license_entity.license_key
        new_max_seats = max(license_entity.max_seats, target_tier.default_max_activations)
        new_features = list(target_tier.default_features)

        days = target_tier.default_expires_in_days
        new_expires_at = (now + timedelta(days=days)) if days is not None else None

        payload: dict[str, Any] = {
            "customer_email": customer_email,
            "customer_id": license_entity.customer_id,
            "expires_at": int(new_expires_at.timestamp()) if new_expires_at else None,
            "features": new_features,
            "issued_at": int(now.timestamp()),
            "license_id": license_entity.id,
            "max_seats": new_max_seats,
            "nonce": secrets.token_hex(8),
            "tier": target_tier.value,
        }
        if license_entity.metadata.get("machine_id"):
            payload["machine_id"] = license_entity.metadata["machine_id"]
        if license_entity.metadata.get("allowed_domains"):
            payload["allowed_domains"] = license_entity.metadata["allowed_domains"]

        if hasattr(self._signer, "stamp_kid"):
            self._signer.stamp_kid(payload)
        new_sig = self._signer.sign(payload)
        new_key = self._signer.format_token(target_tier.value, payload, new_sig)

        prev_keys = list(license_entity.metadata.get("previous_license_keys", []))
        if old_key and old_key != new_key and old_key not in prev_keys:
            prev_keys.append(old_key)
        license_entity.metadata["previous_license_keys"] = prev_keys

        license_entity.tier = target_tier
        license_entity.status = LicenseStatus.ACTIVE
        license_entity.max_seats = new_max_seats
        license_entity.expires_at = new_expires_at
        license_entity.features = tuple(new_features)
        license_entity.signature = new_sig
        license_entity.license_key = new_key

        self._license_repo.save(license_entity)
        return license_entity

    def verify(self, request: LicenseVerifyRequest) -> LicenseVerifyResponse:
        """Validates a license key: checks database existence, revocation ledger, status,
        expiration, and optionally enforces hardware/domain locking (with stateless fallback).
        """
        req_hw = (
            request.hardware_id.strip().lower()
            if (request.hardware_id and request.hardware_id.strip())
            else None
        )
        license_entity = self._license_repo.get_by_key(request.license_key)
        if license_entity is None:
            ok, payload, err = self._signer.verify_token(request.license_key)
            if not ok:
                ok_hmac, payload_hmac, err_hmac = self._hmac_signer.verify_token(
                    request.license_key
                )
                if ok_hmac or err_hmac == "ERR_LICENSE_EXPIRED":
                    ok, payload, err = ok_hmac, payload_hmac, err_hmac

            if not isinstance(payload, dict) or (not ok and err != "ERR_LICENSE_EXPIRED"):
                raise LicenseNotFoundError("License key not found.")

            lic_id = str(payload.get("license_id") or "")
            if lic_id and self.is_revoked_id(lic_id):
                raise LicenseRevokedError("License has been revoked.")

            if err == "ERR_LICENSE_EXPIRED":
                raise LicenseExpiredError("License has expired.")

            stateless_hw = payload.get("machine_id")
            if stateless_hw:
                if not req_hw or req_hw != str(stateless_hw).strip().lower():
                    raise NodeLockViolationError(
                        "License is node-locked to a specific hardware ID."
                    )
            elif req_hw:
                raise NodeLockViolationError(
                    f"Machine hardware ID '{request.hardware_id}' is not activated for this license."
                )

            allowed_domains = payload.get("allowed_domains")
            if isinstance(allowed_domains, list) and not matches_allowed_domains(
                allowed_domains, request.domain
            ):
                raise NodeLockViolationError(
                    f"Domain '{request.domain or ''}' is not authorized for this license."
                )

            exp_ts = payload.get("expires_at")
            exp_dt = (
                datetime.fromtimestamp(exp_ts, tz=timezone.utc)
                if isinstance(exp_ts, (int, float))
                else None
            )
            max_seats_val = int(payload.get("max_seats") or 1)
            return LicenseVerifyResponse(
                valid=True,
                is_valid=True,
                license_id=lic_id,
                tier=str(payload.get("tier") or Tier.COMMUNITY.value),
                status=LicenseStatus.ACTIVE.value,
                expires_at=exp_dt,
                features=list(payload.get("features") or []),
                current_activations=0,
                max_seats=max_seats_val,
                max_activations=max_seats_val,
            )

        # Check status & persistent revocation ledger
        if license_entity.status == LicenseStatus.REVOKED or self.is_revoked_id(
            license_entity.id
        ):
            raise LicenseRevokedError("License has been revoked.")
        if license_entity.status == LicenseStatus.SUSPENDED:
            raise LicenseSuspendedError("License is suspended due to payment delinquency.")

        # Check expiration
        now = datetime.now(timezone.utc)
        if license_entity.status == LicenseStatus.EXPIRED or license_entity.is_expired(now):
            if license_entity.status != LicenseStatus.EXPIRED:
                self._license_repo.update_status(license_entity.id, LicenseStatus.EXPIRED)
            raise LicenseExpiredError("License has expired.")

        # Check embedded machine_id or activated hardware lock
        embedded_hw = license_entity.metadata.get("machine_id")

        if embedded_hw:
            if not req_hw or req_hw != str(embedded_hw).strip().lower():
                raise NodeLockViolationError(
                    "License is node-locked to a specific hardware ID."
                )

        if req_hw:
            activations = self._license_repo.get_activations(license_entity.id)
            activated_hw_ids = {a.hardware_id.strip().lower() for a in activations}
            if req_hw not in activated_hw_ids and (
                not embedded_hw or req_hw != str(embedded_hw).strip().lower()
            ):
                raise NodeLockViolationError(
                    f"Machine hardware ID '{request.hardware_id}' is not activated for this license."
                )

        # Check domain lock if configured on license
        if not license_entity.matches_domain(request.domain):
            raise NodeLockViolationError(
                f"Domain '{request.domain or ''}' is not authorized for this license."
            )

        features = (
            list(license_entity.features)
            if license_entity.features
            else list(license_entity.tier.default_features)
        )
        return LicenseVerifyResponse(
            valid=True,
            is_valid=True,
            license_id=license_entity.id,
            tier=license_entity.tier.value,
            status=license_entity.status.value,
            expires_at=license_entity.expires_at,
            features=features,
            current_activations=license_entity.current_activations,
            max_seats=license_entity.max_seats,
            max_activations=license_entity.max_seats,
        )

    def activate(self, request: LicenseActivateRequest) -> LicenseActivateResponse:
        """Registers a machine hardware UUID against a license, decrementing available seats."""
        license_entity = self._license_repo.get_by_key(request.license_key)
        if license_entity is None:
            raise LicenseNotFoundError("License key not found.")

        if license_entity.status == LicenseStatus.REVOKED or self.is_revoked_id(
            license_entity.id
        ):
            raise LicenseRevokedError("Cannot activate a revoked license.")
        if license_entity.status == LicenseStatus.SUSPENDED:
            raise LicenseSuspendedError("Cannot activate a suspended license.")

        now = datetime.now(timezone.utc)
        if license_entity.status == LicenseStatus.EXPIRED or license_entity.is_expired(now):
            if license_entity.status != LicenseStatus.EXPIRED:
                self._license_repo.update_status(license_entity.id, LicenseStatus.EXPIRED)
            raise LicenseExpiredError("Cannot activate an expired license.")

        hw_norm = request.hardware_id.strip().lower()
        embedded_hw = license_entity.metadata.get("machine_id")
        if embedded_hw and hw_norm != str(embedded_hw).strip().lower():
            raise NodeLockViolationError(
                f"License is node-locked to '{embedded_hw}' and cannot activate '{hw_norm}'."
            )

        # Record activation
        self._license_repo.record_activation(
            license_id=license_entity.id,
            hardware_id=hw_norm,
            machine_name=request.machine_name,
            ip_address=request.ip_address,
        )

        refreshed = self._license_repo.get_by_id(license_entity.id)
        current_acts = refreshed.current_activations if refreshed else 1

        return LicenseActivateResponse(
            activated=True,
            success=True,
            license_id=license_entity.id,
            hardware_id=hw_norm,
            current_activations=current_acts,
            max_seats=license_entity.max_seats,
            max_activations=license_entity.max_seats,
            activated_at=now,
        )

    def list_nodes(self, license_key: str) -> dict[str, Any]:
        """Activated machines for a license, newest first."""
        license_entity = self._license_repo.get_by_key(license_key)
        if license_entity is None:
            raise LicenseNotFoundError("License key not found.")
        nodes = [
            {
                "hardware_id": a.hardware_id,
                "machine_name": a.machine_name,
                "activated_at": a.activated_at.isoformat() if a.activated_at else None,
            }
            for a in self._license_repo.get_activations(license_entity.id)
        ]
        return {
            "license_id": license_entity.id,
            "max_seats": license_entity.max_seats,
            "current_activations": len(nodes),
            "nodes": nodes,
        }

    def release_node(self, license_key: str, hardware_id: str) -> dict[str, Any]:
        """Self-service seat release, rate limited per license (NODE_RELEASES_PER_24H)."""
        from app.config import get_settings

        license_entity = self._license_repo.get_by_key(license_key)
        if license_entity is None:
            raise LicenseNotFoundError("License key not found.")
        if license_entity.status == LicenseStatus.REVOKED or self.is_revoked_id(license_entity.id):
            raise LicenseRevokedError("Cannot manage nodes of a revoked license.")
        remaining = self._license_repo.release_activation(
            license_entity.id, hardware_id, get_settings().NODE_RELEASES_PER_24H
        )
        return {
            "released": True,
            "license_id": license_entity.id,
            "hardware_id": hardware_id.strip().lower(),
            "current_activations": remaining,
            "max_seats": license_entity.max_seats,
        }

    def revoke(self, request: LicenseRevokeRequest) -> LicenseRevokeResponse:
        """Immediately revokes a license and records it in the permanent revocation ledger."""
        license_entity = self._license_repo.get_by_key(request.license_key)
        if license_entity is None:
            raise LicenseNotFoundError("License key not found.")

        license_entity.revoke(request.reason)
        if self._conn is not None:
            from app.infrastructure.database.connection import transaction
            with transaction(self._conn):
                self._license_repo.save(license_entity)
                self._license_repo.record_revocation(license_entity.id, request.reason)
        else:
            self._license_repo.save(license_entity)
            if hasattr(self._license_repo, "record_revocation"):
                self._license_repo.record_revocation(license_entity.id, request.reason)

        return LicenseRevokeResponse(
            success=True,
            license_key=request.license_key,
            status="revoked",
            revoked_at=datetime.now(timezone.utc),
        )

    def is_revoked_id(self, license_id: Optional[str]) -> bool:
        """Checks whether a license ID appears in the persistent revocation ledger."""
        if not license_id:
            return False
        if hasattr(self._license_repo, "is_revoked"):
            return self._license_repo.is_revoked(license_id)
        return False

    def get_public_key_hex(self) -> str:
        """Returns the active hex-encoded Ed25519 public verification key."""
        if hasattr(self._signer, "get_public_key_hex"):
            return self._signer.get_public_key_hex()
        if hasattr(self._signer, "public_key_bytes") and self._signer.public_key_bytes:
            return self._signer.public_key_bytes.hex()
        return ""
