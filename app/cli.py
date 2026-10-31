"""KeyForge Standalone Developer CLI Tool.

File: app/cli.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from typing import NoReturn, Optional
import uuid

import click
from pydantic import ValidationError

from app import __version__
from app.application.dtos.license_dtos import (
    LicenseActivateRequest,
    LicenseIssueRequest,
    LicenseRevokeRequest,
    LicenseVerifyRequest,
)
from app.application.dtos.quota_dtos import (
    QuotaBalanceRequest,
    QuotaDeductRequest,
    QuotaReplenishRequest,
)
from app.application.services.license_service import LicenseService
from app.application.services.quota_service import QuotaService
from app.config import get_settings
from app.domain.exceptions import DomainError
from app.infrastructure.database.connection import create_connection
from app.infrastructure.database.migrations import run_migrations
from app.infrastructure.repositories.sqlite_customer_repo import SqliteCustomerRepo
from app.infrastructure.repositories.sqlite_license_repo import SqliteLicenseRepo
from app.infrastructure.repositories.sqlite_quota_repo import SqliteQuotaRepo
from app.infrastructure.security.offline_validator import validate_offline


def _open_migrated_db() -> sqlite3.Connection:
    """Opens SQLite connection and ensures schema migrations are applied."""
    conn = create_connection()
    try:
        run_migrations(conn)
    except Exception:
        conn.close()
        raise
    return conn


def _resolve_key(positional_key: Optional[str], option_key: Optional[str]) -> str:
    chosen = (positional_key or option_key or "").strip()
    if not chosen:
        _exit_cli_error(ValueError("A license key argument or --key option is required."))
    return chosen


def _exit_cli_error(exc: Exception) -> NoReturn:
    if isinstance(exc, DomainError):
        payload = {"success": False, "error": exc.to_dict()}
    elif isinstance(exc, ValidationError):
        payload = {
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid CLI input parameters.",
                "details": [
                    {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", ""))}
                    for e in exc.errors()
                ],
            },
        }
    else:
        payload = {
            "success": False,
            "error": {"code": "CLI_ERROR", "message": str(exc)},
        }
    click.echo(json.dumps(payload, indent=2, default=str), err=True)
    sys.exit(1)


@click.group()
@click.version_option(version=__version__, prog_name="keyforge")
def cli() -> None:
    """KeyForge — Cryptographic Licensing & Quota-Metering Gateway CLI."""


@cli.command("issue")
@click.option("--email", "-e", required=True, help="Customer email address.")
@click.option(
    "--tier",
    "-t",
    default="pro",
    type=click.Choice(["community", "pro", "studio", "lifetime"], case_sensitive=False),
    help="Entitlement tier.",
)
@click.option(
    "--seats",
    "-s",
    default=None,
    type=int,
    help="Maximum activation seats (defaults to tier entitlement).",
)
@click.option(
    "--days",
    "-d",
    default=None,
    type=int,
    help="Validity duration in days (defaults to tier duration; perpetual for lifetime).",
)
@click.option(
    "--algo",
    "-a",
    default="ed25519",
    type=click.Choice(["ed25519", "hmac-sha256"], case_sensitive=False),
    help="Cryptographic signing algorithm.",
)
@click.option(
    "--machine-id",
    default=None,
    help="Optional hardware fingerprint embedded into the signed token.",
)
@click.option(
    "--domain",
    "domains",
    multiple=True,
    help="Optional allowed domain pattern (repeatable, e.g. --domain *.acme.io).",
)
def issue_license_cmd(
    email: str,
    tier: str,
    seats: Optional[int],
    days: Optional[int],
    algo: str,
    machine_id: Optional[str],
    domains: tuple[str, ...],
) -> None:
    """Issues a new cryptographically signed license key."""
    conn = _open_migrated_db()
    try:
        svc = LicenseService(
            license_repo=SqliteLicenseRepo(conn),
            customer_repo=SqliteCustomerRepo(conn),
            quota_repo=SqliteQuotaRepo(conn),
            conn=conn,
        )
        res = svc.issue(
            LicenseIssueRequest(
                customer_email=email,
                tier=tier.lower(),
                max_seats=seats,
                expires_in_days=days,
                signing_algorithm=algo.lower(),
                machine_id=machine_id,
                allowed_domains=list(domains) if domains else None,
            )
        )
        click.echo(json.dumps(res.model_dump(), indent=2, default=str))
    except (DomainError, ValidationError, ValueError) as exc:
        _exit_cli_error(exc)
    finally:
        conn.close()


@cli.command("verify")
@click.argument("license_key", required=False)
@click.option("--key", "key_opt", default=None, help="License token (alternative to positional argument).")
@click.option("--offline", is_flag=True, help="Validate completely offline using Ed25519 public key.")
@click.option("--public-key", "-pk", default=None, help="Hex-encoded Ed25519 public key.")
@click.option("--hardware-id", "-hw", default=None, help="Machine hardware ID for node-locking validation.")
@click.option("--domain", default=None, help="Domain name for domain-lock validation.")
@click.option("--pure-python", is_flag=True, help="Force pure-Python RFC 8032 Ed25519 math during offline check.")
def verify_license_cmd(
    license_key: Optional[str],
    key_opt: Optional[str],
    offline: bool,
    public_key: Optional[str],
    hardware_id: Optional[str],
    domain: Optional[str],
    pure_python: bool,
) -> None:
    """Verifies a license token online (database + ledger) or offline (air-gapped Ed25519)."""
    resolved_key = _resolve_key(license_key, key_opt)
    if offline:
        settings = get_settings()
        pk = public_key or settings.ED25519_PUBLIC_KEY_HEX
        if not pk:
            _exit_cli_error(ValueError("Public key must be provided for offline verification."))
        valid, payload, err = validate_offline(
            license_token=resolved_key,
            public_key_hex=pk,
            expected_machine_id=hardware_id,
            force_pure_python=pure_python,
        )
        click.echo(
            json.dumps(
                {"valid": valid, "payload": payload, "error": err},
                indent=2,
                default=str,
            )
        )
        if not valid:
            sys.exit(1)
        return

    conn = _open_migrated_db()
    try:
        svc = LicenseService(
            license_repo=SqliteLicenseRepo(conn),
            customer_repo=SqliteCustomerRepo(conn),
            quota_repo=SqliteQuotaRepo(conn),
            conn=conn,
        )
        res = svc.verify(
            LicenseVerifyRequest(
                license_key=resolved_key,
                hardware_id=hardware_id,
                domain=domain,
            )
        )
        click.echo(json.dumps(res.model_dump(), indent=2, default=str))
        if not res.valid:
            sys.exit(1)
    except (DomainError, ValidationError, ValueError) as exc:
        _exit_cli_error(exc)
    finally:
        conn.close()


@cli.command("activate")
@click.argument("license_key", required=False)
@click.option("--key", "key_opt", default=None, help="License token (alternative to positional argument).")
@click.option("--hardware-id", "-hw", required=True, help="Machine UUID or hardware fingerprint.")
@click.option("--machine-name", "-m", default="developer-node", help="Friendly workstation name.")
def activate_cmd(
    license_key: Optional[str],
    key_opt: Optional[str],
    hardware_id: str,
    machine_name: str,
) -> None:
    """Binds a machine hardware UUID to an active license."""
    resolved_key = _resolve_key(license_key, key_opt)
    conn = _open_migrated_db()
    try:
        svc = LicenseService(
            license_repo=SqliteLicenseRepo(conn),
            customer_repo=SqliteCustomerRepo(conn),
            quota_repo=SqliteQuotaRepo(conn),
            conn=conn,
        )
        res = svc.activate(
            LicenseActivateRequest(
                license_key=resolved_key,
                hardware_id=hardware_id,
                machine_name=machine_name,
            )
        )
        click.echo(json.dumps(res.model_dump(), indent=2, default=str))
    except (DomainError, ValidationError, ValueError) as exc:
        _exit_cli_error(exc)
    finally:
        conn.close()


@cli.command("revoke")
@click.argument("license_key", required=False)
@click.option("--key", "key_opt", default=None, help="License token (alternative to positional argument).")
@click.option("--reason", "-r", default="Administrative CLI revocation", help="Audit revocation reason.")
def revoke_cmd(
    license_key: Optional[str],
    key_opt: Optional[str],
    reason: str,
) -> None:
    """Immediately revokes a license key and persists it in the revocation ledger."""
    resolved_key = _resolve_key(license_key, key_opt)
    conn = _open_migrated_db()
    try:
        svc = LicenseService(
            license_repo=SqliteLicenseRepo(conn),
            customer_repo=SqliteCustomerRepo(conn),
            quota_repo=SqliteQuotaRepo(conn),
            conn=conn,
        )
        res = svc.revoke(LicenseRevokeRequest(license_key=resolved_key, reason=reason))
        click.echo(json.dumps(res.model_dump(), indent=2, default=str))
    except (DomainError, ValidationError, ValueError) as exc:
        _exit_cli_error(exc)
    finally:
        conn.close()


@cli.group("quota")
def quota_group() -> None:
    """Token-bucket usage quota operations."""


@quota_group.command("deduct")
@click.argument("license_key", required=False)
@click.option("--key", "key_opt", default=None, help="License token (alternative to positional argument).")
@click.option("--credits", "-c", default=1, type=int, help="Credits to consume.")
@click.option("--idempotency-key", "-i", default=None, help="Unique idempotency key (auto-generated if omitted).")
@click.option("--event-type", default="cli_call", help="Event category tag.")
def quota_deduct_cmd(
    license_key: Optional[str],
    key_opt: Optional[str],
    credits: int,
    idempotency_key: Optional[str],
    event_type: str,
) -> None:
    """Deducts usage credits from a license balance."""
    resolved_key = _resolve_key(license_key, key_opt)
    resolved_idem = idempotency_key or f"cli-{uuid.uuid4().hex}"
    conn = _open_migrated_db()
    try:
        svc = QuotaService(
            quota_repo=SqliteQuotaRepo(conn),
            license_repo=SqliteLicenseRepo(conn),
        )
        res = svc.deduct(
            QuotaDeductRequest(
                license_key=resolved_key,
                credits=credits,
                idempotency_key=resolved_idem,
                event_type=event_type,
            )
        )
        click.echo(json.dumps(res.model_dump(), indent=2, default=str))
    except (DomainError, ValidationError, ValueError) as exc:
        _exit_cli_error(exc)
    finally:
        conn.close()


@quota_group.command("replenish")
@click.argument("license_key", required=False)
@click.option("--key", "key_opt", default=None, help="License token (alternative to positional argument).")
@click.option("--credits", "-c", required=True, type=int, help="Credits to add or reset to.")
@click.option(
    "--reset-cycle",
    is_flag=True,
    help="Reset billing cycle allowance and consumed counter instead of topping up.",
)
def quota_replenish_cmd(
    license_key: Optional[str],
    key_opt: Optional[str],
    credits: int,
    reset_cycle: bool,
) -> None:
    """Replenishes or resets billing-cycle credits for a license."""
    resolved_key = _resolve_key(license_key, key_opt)
    conn = _open_migrated_db()
    try:
        svc = QuotaService(
            quota_repo=SqliteQuotaRepo(conn),
            license_repo=SqliteLicenseRepo(conn),
        )
        res = svc.replenish(
            QuotaReplenishRequest(
                license_key=resolved_key,
                credits=credits,
                reset_cycle=reset_cycle,
            )
        )
        click.echo(json.dumps(res.model_dump(), indent=2, default=str))
    except (DomainError, ValidationError, ValueError) as exc:
        _exit_cli_error(exc)
    finally:
        conn.close()


@quota_group.command("balance")
@click.argument("license_key", required=False)
@click.option("--key", "key_opt", default=None, help="License token (alternative to positional argument).")
def quota_balance_cmd(
    license_key: Optional[str],
    key_opt: Optional[str],
) -> None:
    """Checks the real-time credit balance of a license."""
    resolved_key = _resolve_key(license_key, key_opt)
    conn = _open_migrated_db()
    try:
        svc = QuotaService(
            quota_repo=SqliteQuotaRepo(conn),
            license_repo=SqliteLicenseRepo(conn),
        )
        res = svc.get_balance(QuotaBalanceRequest(license_key=resolved_key))
        click.echo(json.dumps(res.model_dump(), indent=2, default=str))
    except (DomainError, ValidationError, ValueError) as exc:
        _exit_cli_error(exc)
    finally:
        conn.close()


@cli.command("serve")
@click.option("--host", default="0.0.0.0", help="Binding host.")
@click.option("--port", default=8000, type=int, help="HTTP listening port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development.")
def serve_cmd(host: str, port: int, reload: bool) -> None:
    """Starts the KeyForge API Gateway uvicorn web server."""
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
