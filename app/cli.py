"""KeyFlint Standalone Developer CLI Tool.

File: app/cli.py
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import sys
from pathlib import Path
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
from app.infrastructure.security.ed25519_signer import Ed25519Signer
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
@click.version_option(version=__version__, prog_name="keyflint")
def cli() -> None:
    """KeyFlint — Cryptographic Licensing & Quota-Metering Gateway CLI."""


@cli.command("issue")
@click.option("--email", "-e", required=True, help="Customer email address.")
@click.option(
    "--tier",
    "-t",
    default="pro",
    type=click.Choice(["community", "indie", "agency", "pro", "studio", "lifetime", "despacho_basico", "despacho_pro", "despacho_empresa"], case_sensitive=False),
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
        pk = public_key or settings.ED25519_PUBLIC_KEY_HEX or Ed25519Signer().get_public_key_hex()
        if not pk:
            _exit_cli_error(ValueError("Public key must be provided for offline verification."))
        valid, payload, err = validate_offline(
            license_token=resolved_key,
            public_key_hex=pk,
            expected_machine_id=hardware_id,
            expected_domain=domain,
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


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_ENV_TEMPLATES = {
    "development": ".env.example",
    "production": ".env.production.example",
}
_FALLBACK_ENV_TEMPLATE = """# KeyFlint environment (generated by `keyflint init`)
ENVIRONMENT={environment}
DATABASE_URL=sqlite:///data/keyforge.db
SECRET_KEY=
ED25519_PRIVATE_KEY_HEX=
ED25519_PUBLIC_KEY_HEX=
ADMIN_API_KEY=
BILLING_MODE=mock
STRIPE_WEBHOOK_SECRET=
LEMONSQUEEZY_WEBHOOK_SECRET=
"""


def _generate_secrets() -> dict[str, str]:
    """Generates fresh production-grade secrets (never printed to stdout)."""
    private_hex = secrets.token_hex(32)
    signer = Ed25519Signer(private_key_hex=private_hex)
    return {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "ED25519_PRIVATE_KEY_HEX": private_hex,
        "ED25519_PUBLIC_KEY_HEX": signer.get_public_key_hex(),
        "ADMIN_API_KEY": "kf_" + secrets.token_urlsafe(32),
    }


def _render_env(template: str, values: dict[str, str]) -> str:
    """Replaces KEY=value lines in-place (keeping comments/order) and appends missing keys."""
    rendered = template
    for name, value in values.items():
        pattern = re.compile(rf"^{re.escape(name)}=.*$", re.MULTILINE)
        if pattern.search(rendered):
            rendered = pattern.sub(lambda _m, n=name, v=value: f"{n}={v}", rendered, count=1)
        else:
            rendered = rendered.rstrip("\n") + f"\n{name}={value}\n"
    return rendered if rendered.endswith("\n") else rendered + "\n"


@cli.command("init")
@click.option(
    "--env",
    "environment",
    default="development",
    type=click.Choice(["development", "production"], case_sensitive=False),
    help="Target environment; selects .env.example or .env.production.example as template.",
)
@click.option(
    "--output",
    "-o",
    default=".env",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Destination file (default: ./.env).",
)
@click.option(
    "--template",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Custom template file (defaults to the project template for --env).",
)
@click.option("--force", is_flag=True, help="Overwrite the destination file if it already exists.")
def init_cmd(environment: str, output: Path, template: Optional[Path], force: bool) -> None:
    """Generates a .env with a fresh Ed25519 keypair, SECRET_KEY and ADMIN_API_KEY."""
    environment = environment.lower()
    try:
        if output.exists() and not force:
            raise ValueError(
                f"{output} already exists. Re-run with --force to overwrite it "
                "(existing licenses stay valid only with the current Ed25519 key)."
            )

        template_path = template
        if template_path is None:
            name = _ENV_TEMPLATES[environment]
            for candidate in (Path.cwd() / name, _PROJECT_ROOT / name):
                if candidate.is_file():
                    template_path = candidate
                    break
        base = (
            template_path.read_text(encoding="utf-8")
            if template_path is not None
            else _FALLBACK_ENV_TEMPLATE.format(environment=environment)
        )

        generated = _generate_secrets()
        # Empty webhook secrets make a production gateway refuse to start; fill them with random
        # values (still listed in fill_manually) so the server boots before billing is connected.
        for name, prefix in (("STRIPE_WEBHOOK_SECRET", "whsec_"), ("LEMONSQUEEZY_WEBHOOK_SECRET", "")):
            if re.search(rf"^{name}=\s*$", base, re.MULTILINE):
                generated[name] = prefix + secrets.token_urlsafe(32)
        content = _render_env(base, {"ENVIRONMENT": environment, **generated})

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        try:
            os.chmod(output, 0o600)
        except OSError:
            pass

        pending = []
        if environment == "production":
            pending = [
                "STRIPE_WEBHOOK_SECRET",
                "LEMONSQUEEZY_WEBHOOK_SECRET",
                "STRIPE_SECRET_KEY",
                "LEMONSQUEEZY_CHECKOUT_URL",
                "PUBLIC_BASE_URL",
            ]
        click.echo(
            json.dumps(
                {
                    "success": True,
                    "path": str(output),
                    "environment": environment,
                    "template": str(template_path) if template_path else "built-in",
                    "generated": sorted(generated),
                    "ED25519_PUBLIC_KEY_HEX": generated["ED25519_PUBLIC_KEY_HEX"],
                    "fill_manually": pending,
                    "warning": "Back up ED25519_PRIVATE_KEY_HEX: losing it invalidates every issued license.",
                },
                indent=2,
            )
        )
    except (OSError, ValueError) as exc:
        _exit_cli_error(exc)


@cli.command("resend-license")
@click.argument("license_key", required=False)
@click.option("--key", "key_opt", default=None, help="License token (alternative to positional argument).")
@click.option("--email", "-e", default=None, help="Resend every license owned by this customer email.")
@click.option("--to", default=None, help="Override recipient address.")
@click.option("--failed", "failed_only", is_flag=True, help="Retry every license whose last email failed.")
def resend_license_cmd(
    license_key: Optional[str],
    key_opt: Optional[str],
    email: Optional[str],
    to: Optional[str],
    failed_only: bool,
) -> None:
    """Re-sends license emails (by key, by customer email, or all failed deliveries)."""
    from app.infrastructure.email.license_delivery import build_billing_service

    conn = _open_migrated_db()
    try:
        billing = build_billing_service(conn)
        if failed_only:
            click.echo(json.dumps({"success": True, "data": billing.retry_failed_license_emails()}, indent=2))
            return
        keys: list[str]
        if email:
            customer = SqliteCustomerRepo(conn).get_by_email(email.strip())
            if customer is None:
                _exit_cli_error(ValueError(f"No customer with email {email!r}."))
            keys = [lic.license_key for lic in SqliteLicenseRepo(conn).list_by_customer_id(customer.id)]
            if not keys:
                _exit_cli_error(ValueError(f"Customer {email!r} has no licenses."))
        else:
            keys = [_resolve_key(license_key, key_opt)]
        results = {k[:24] + "...": billing.deliver_license_email(k, recipient=to or email) for k in keys}
        ok = all(results.values())
        click.echo(json.dumps({"success": ok, "data": {"email_delivered": results}}, indent=2))
        if not ok:
            sys.exit(1)
    except (DomainError, ValueError) as exc:
        _exit_cli_error(exc)
    finally:
        conn.close()


@cli.command("serve")
@click.option("--host", default="0.0.0.0", help="Binding host.")
@click.option("--port", default=8000, type=int, help="HTTP listening port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload for development.")
def serve_cmd(host: str, port: int, reload: bool) -> None:
    """Starts the KeyFlint API Gateway uvicorn web server."""
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
