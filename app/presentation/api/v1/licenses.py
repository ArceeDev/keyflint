"""License Management REST API Router."""

from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.application.dtos.license_dtos import (
    LicenseActivateRequest,
    LicenseIssueRequest,
    LicenseNodeReleaseRequest,
    LicenseNodesRequest,
    LicenseRevokeRequest,
    LicenseVerifyRequest,
)
from app.application.services.license_service import LicenseService
from app.domain.entities.license import License, LicenseStatus, Tier, matches_allowed_domains
from app.presentation.dependencies import (
    build_response_metadata,
    get_license_service,
    require_admin_access,
)

router = APIRouter(prefix="/api/v1/licenses", tags=["Licenses"])


@router.get("/public-key")
def get_public_key(
    http_request: Request,
    license_service: LicenseService = Depends(get_license_service),
) -> dict[str, Any]:
    """Returns the Ed25519 public verification key for air-gapped client SDKs."""
    signer = license_service._signer
    pub_hex = signer.get_public_key_hex() if hasattr(signer, "get_public_key_hex") else ""
    keys = signer.public_keys() if hasattr(signer, "public_keys") else []
    # KEYFLINT_PUBLIC_KEYS-compatible string: all "kid=hex" (kid-less keys labelled "legacy-N")
    # or all bare hex when no key has a kid. SDKs try every key for tokens without kid.
    if any(k["kid"] for k in keys):
        ring_env = ",".join(f"{k['kid'] or f'legacy-{i}'}={k['public_key_hex']}" for i, k in enumerate(keys))
    else:
        ring_env = ",".join(k["public_key_hex"] for k in keys)
    return {
        "success": True,
        "data": {
            "algorithm": "Ed25519",
            "public_key_hex": pub_hex,
            "kid": getattr(signer, "kid", None),
            "keys": keys,
            "keyring": ring_env,
        },
        "metadata": build_response_metadata(http_request),
    }


@router.post("/issue", status_code=200, dependencies=[Depends(require_admin_access)])
def issue_license(
    request: LicenseIssueRequest,
    http_request: Request,
    license_service: LicenseService = Depends(get_license_service),
) -> dict[str, Any]:
    """Issues a cryptographically signed license token."""
    res = license_service.issue(request)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


@router.get("/by-customer", dependencies=[Depends(require_admin_access)])
def list_customer_licenses(
    http_request: Request,
    email: str = Query(..., min_length=3),
    license_service: LicenseService = Depends(get_license_service),
) -> dict[str, Any]:
    """Returns active licenses belonging to a customer by email (admin only)."""
    cleaned = email.strip().lower()
    customer = license_service._customer_repo.get_by_email(cleaned)
    if not customer:
        return {
            "success": True,
            "data": [],
            "metadata": build_response_metadata(http_request),
        }

    licenses = license_service._license_repo.list_by_customer_id(customer.id)
    now_dt = datetime.now(timezone.utc)
    active = []
    for lic in licenses:
        if (
            lic.status in (LicenseStatus.ACTIVE, LicenseStatus.GRACE_PERIOD)
            and not lic.is_expired(now_dt)
            and not license_service.is_revoked_id(lic.id)
        ):
            quota = license_service._quota_repo.get_by_license_id(lic.id)
            credits = int(quota.balance) if quota is not None else 0
            tier_display = lic.tier.value.replace("_", " ").upper()
            seats_suffix = f" ({lic.max_seats} puestos)" if lic.max_seats > 1 else ""
            active.append({
                "key": lic.license_key,
                "tier": lic.tier.value,
                "status": lic.status.value,
                "name": f"Licencia {tier_display}{seats_suffix}",
                "credits": credits,
                "max_seats": lic.max_seats,
                "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
            })
    active.sort(key=lambda item: (item["tier"] == Tier.COMMUNITY.value, -item["credits"]))
    return {
        "success": True,
        "data": active,
        "metadata": build_response_metadata(http_request),
    }


@router.post("/verify")
def verify_license(
    request: LicenseVerifyRequest,
    http_request: Request,
    response: Response,
    license_service: LicenseService = Depends(get_license_service),
) -> dict[str, Any]:
    """Validates a license token online with database verification and stateless fallback."""
    meta = build_response_metadata(http_request)
    raw_key = (request.license_key or "").strip()
    if not raw_key:
        raise HTTPException(
            status_code=422, detail="license_key cannot be empty or whitespace"
        )

    if not raw_key.startswith("LIC-") or "." not in raw_key:
        raise HTTPException(status_code=400, detail="Malformed license key format")

    parts = raw_key.split(".")
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail="Malformed license key format: invalid dot delimiter count",
        )

    req_hw = (
        request.hardware_id.strip().lower()
        if (request.hardware_id and request.hardware_id.strip())
        else None
    )

    # 1. Check in database first
    db_license: License | None = license_service._license_repo.get_by_key(raw_key)
    if db_license is not None:
        features = list(db_license.features)
        if not features:
            ok_tok, token_payload, _ = license_service._signer.verify_token(raw_key)
            if not ok_tok:
                ok_tok, token_payload, _ = license_service._hmac_signer.verify_token(raw_key)
            if ok_tok and isinstance(token_payload, dict):
                features = list(token_payload.get("features", []))
        if not features:
            features = list(db_license.tier.default_features)

        if db_license.status == LicenseStatus.REVOKED or license_service.is_revoked_id(
            db_license.id
        ):
            return {
                "success": True,
                "data": {
                    "valid": False,
                    "is_valid": False,
                    "status": "revoked",
                    "license_id": db_license.id,
                    "tier": db_license.tier.value,
                    "features": features,
                },
                "metadata": meta,
            }

        if db_license.status == LicenseStatus.SUSPENDED:
            return {
                "success": True,
                "data": {
                    "valid": False,
                    "is_valid": False,
                    "status": "suspended",
                    "license_id": db_license.id,
                    "tier": db_license.tier.value,
                    "features": features,
                },
                "metadata": meta,
            }

        now_dt = datetime.now(timezone.utc)
        if db_license.status == LicenseStatus.EXPIRED or db_license.is_expired(now_dt):
            if db_license.status != LicenseStatus.EXPIRED:
                license_service._license_repo.update_status(
                    db_license.id, LicenseStatus.EXPIRED
                )
            return {
                "success": True,
                "data": {
                    "valid": False,
                    "is_valid": False,
                    "status": "expired",
                    "license_id": db_license.id,
                    "tier": db_license.tier.value,
                    "features": features,
                },
                "metadata": meta,
            }

        # Embedded machine_id or activated hardware_id verification
        embedded_hw = db_license.metadata.get("machine_id")
        if embedded_hw:
            if not req_hw or req_hw != str(embedded_hw).strip().lower():
                return {
                    "success": True,
                    "data": {
                        "valid": False,
                        "is_valid": False,
                        "status": "node_lock_violation",
                        "license_id": db_license.id,
                        "tier": db_license.tier.value,
                        "features": features,
                    },
                    "metadata": meta,
                }

        if req_hw:
            activations = license_service._license_repo.get_activations(db_license.id)
            active_hw_ids = {a.hardware_id.strip().lower() for a in activations}
            if req_hw not in active_hw_ids and (
                not embedded_hw or req_hw != str(embedded_hw).strip().lower()
            ):
                return {
                    "success": True,
                    "data": {
                        "valid": False,
                        "is_valid": False,
                        "status": "node_lock_violation",
                        "license_id": db_license.id,
                        "tier": db_license.tier.value,
                        "features": features,
                    },
                    "metadata": meta,
                }

        if not db_license.matches_domain(request.domain):
            return {
                "success": True,
                "data": {
                    "valid": False,
                    "is_valid": False,
                    "status": "domain_lock_violation",
                    "license_id": db_license.id,
                    "tier": db_license.tier.value,
                    "features": features,
                },
                "metadata": meta,
            }

        if db_license.status == LicenseStatus.GRACE_PERIOD:
            response.headers["X-Subscription-Warning"] = "Account in payment grace period"
            return {
                "success": True,
                "data": {
                    "valid": True,
                    "is_valid": True,
                    "status": "grace_period",
                    "license_id": db_license.id,
                    "tier": db_license.tier.value,
                    "features": features,
                    "current_activations": db_license.current_activations,
                    "max_seats": db_license.max_seats,
                    "expires_at": db_license.expires_at.isoformat()
                    if db_license.expires_at
                    else None,
                },
                "metadata": meta,
            }

        return {
            "success": True,
            "data": {
                "valid": True,
                "is_valid": True,
                "status": "active",
                "license_id": db_license.id,
                "tier": db_license.tier.value,
                "features": features,
                "current_activations": db_license.current_activations,
                "max_seats": db_license.max_seats,
                "expires_at": db_license.expires_at.isoformat()
                if db_license.expires_at
                else None,
            },
            "metadata": meta,
        }

    # 2. Stateless cryptographic evaluation fallback
    ok, payload, err = license_service._signer.verify_token(raw_key)
    if not ok:
        ok_hmac, payload_hmac, err_hmac = license_service._hmac_signer.verify_token(raw_key)
        if ok_hmac or err_hmac == "ERR_LICENSE_EXPIRED":
            ok, payload, err = ok_hmac, payload_hmac, err_hmac

    if isinstance(payload, dict) and (ok or err == "ERR_LICENSE_EXPIRED"):
        lic_id_probe = str(payload.get("license_id") or "")
        if lic_id_probe and license_service.is_revoked_id(lic_id_probe):
            return {
                "success": True,
                "data": {
                    "valid": False,
                    "is_valid": False,
                    "status": "revoked",
                    "license_id": lic_id_probe,
                    "tier": str(payload.get("tier") or Tier.COMMUNITY.value),
                    "features": list(payload.get("features") or []),
                },
                "metadata": meta,
            }

    if not ok or not isinstance(payload, dict):
        return {
            "success": True,
            "data": {
                "valid": False,
                "is_valid": False,
                "status": "expired" if err == "ERR_LICENSE_EXPIRED" else "invalid",
                "error": err,
            },
            "metadata": meta,
        }

    lic_id = str(payload.get("license_id") or "")
    tier_val = str(payload.get("tier") or Tier.COMMUNITY.value)
    features = list(payload.get("features") or [])

    if lic_id and license_service.is_revoked_id(lic_id):
        return {
            "success": True,
            "data": {
                "valid": False,
                "is_valid": False,
                "status": "revoked",
                "license_id": lic_id,
                "tier": tier_val,
                "features": features,
            },
            "metadata": meta,
        }

    expires_at = payload.get("expires_at")
    now_ts = int(time.time())
    if isinstance(expires_at, (int, float)) and now_ts > expires_at:
        return {
            "success": True,
            "data": {
                "valid": False,
                "is_valid": False,
                "status": "expired",
                "license_id": lic_id,
                "tier": tier_val,
                "features": features,
            },
            "metadata": meta,
        }

    stateless_hw = payload.get("machine_id")
    if stateless_hw:
        if not req_hw or req_hw != str(stateless_hw).strip().lower():
            return {
                "success": True,
                "data": {
                    "valid": False,
                    "is_valid": False,
                    "status": "node_lock_violation",
                    "license_id": lic_id,
                    "tier": tier_val,
                    "features": features,
                },
                "metadata": meta,
            }
    elif req_hw:
        return {
            "success": True,
            "data": {
                "valid": False,
                "is_valid": False,
                "status": "node_lock_violation",
                "license_id": lic_id,
                "tier": tier_val,
                "features": features,
            },
            "metadata": meta,
        }

    allowed_domains = payload.get("allowed_domains")
    if isinstance(allowed_domains, list) and not matches_allowed_domains(
        allowed_domains, request.domain
    ):
        return {
            "success": True,
            "data": {
                "valid": False,
                "is_valid": False,
                "status": "domain_lock_violation",
                "license_id": lic_id,
                "tier": tier_val,
                "features": features,
            },
            "metadata": meta,
        }

    return {
        "success": True,
        "data": {
            "valid": True,
            "is_valid": True,
            "status": "active",
            "license_id": lic_id,
            "tier": tier_val,
            "features": features,
            "max_seats": payload.get("max_seats", 1),
            "current_activations": 0,
        },
        "metadata": meta,
    }


@router.post("/activate")
def activate_license(
    request: LicenseActivateRequest,
    http_request: Request,
    license_service: LicenseService = Depends(get_license_service),
) -> dict[str, Any]:
    """Binds a machine hardware UUID to an active license."""
    res = license_service.activate(request)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }


@router.post("/nodes")
def list_license_nodes(
    request: LicenseNodesRequest,
    http_request: Request,
    license_service: LicenseService = Depends(get_license_service),
) -> dict[str, Any]:
    """Lists the machines holding seats on a license (POST keeps the key out of URLs and logs)."""
    return {
        "success": True,
        "data": license_service.list_nodes(request.license_key),
        "metadata": build_response_metadata(http_request),
    }


@router.post("/nodes/release")
def release_license_node(
    request: LicenseNodeReleaseRequest,
    http_request: Request,
    license_service: LicenseService = Depends(get_license_service),
) -> dict[str, Any]:
    """Frees a seat (rebuilt container, new laptop). Limited to NODE_RELEASES_PER_24H per license."""
    return {
        "success": True,
        "data": license_service.release_node(request.license_key, request.hardware_id),
        "metadata": build_response_metadata(http_request),
    }


@router.post("/revoke", dependencies=[Depends(require_admin_access)])
def revoke_license(
    request: LicenseRevokeRequest,
    http_request: Request,
    license_service: LicenseService = Depends(get_license_service),
) -> dict[str, Any]:
    """Blacklists and revokes a license key."""
    res = license_service.revoke(request)
    return {
        "success": True,
        "data": res.model_dump(),
        "metadata": build_response_metadata(http_request),
    }
