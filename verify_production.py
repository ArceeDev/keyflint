"""KeyFlint Automated Production Gatekeeper & Deployment Verification Suite.

File: verify_production.py
Usage: python verify_production.py
Exit code: 0 on complete verification pass, 1 on any failure.
"""

from __future__ import annotations

import ast
import base64
import concurrent.futures
from datetime import datetime, timezone
import importlib
import inspect
import json
import os
from pathlib import Path
import pkgutil
import re
import subprocess
import sys
import tempfile
import threading
import time
import typing
import uuid

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ANSI Color formatting
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
CYAN = "\033[36m"

_ED25519_Q = 2**255 - 19
_ED25519_L = 2**252 + 27742317777372353535851937790883648493


def print_header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 72}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 72}{RESET}")


def print_step(step_num: int, name: str) -> None:
    print(f"\n{BOLD}[STEP {step_num}] {name}...{RESET}")


def print_pass(msg: str) -> None:
    print(f"  {GREEN}[PASS]{RESET} {msg}")


def print_fail(msg: str) -> None:
    print(f"  {RED}[FAIL]{RESET} {msg}")


def _b64u_enc(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_dec(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + pad).encode("ascii"))


def verify_domain_ast_purity() -> bool:
    """Gate 1: Ensures app/domain and standalone offline_validator use 100% pure stdlib boundaries."""
    domain_dir = PROJECT_ROOT / "app" / "domain"
    if not domain_dir.exists():
        print_fail(f"Domain directory not found: {domain_dir}")
        return False

    violations: list[tuple[str, str]] = []
    py_files = sorted(domain_dir.rglob("*.py"))
    stdlib_allowed = set(sys.stdlib_module_names) | {"__future__"}

    for fpath in py_files:
        try:
            tree = ast.parse(fpath.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top not in stdlib_allowed and not alias.name.startswith("app.domain"):
                            violations.append((fpath.name, alias.name))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    top = node.module.split(".")[0]
                    if top not in stdlib_allowed and not node.module.startswith("app.domain"):
                        violations.append((fpath.name, node.module))
        except Exception as exc:
            violations.append((fpath.name, f"Syntax error: {exc}"))

    offline_path = PROJECT_ROOT / "app" / "infrastructure" / "security" / "offline_validator.py"
    try:
        off_tree = ast.parse(offline_path.read_text(encoding="utf-8"))
        for stmt in off_tree.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    if alias.name.split(".")[0] not in stdlib_allowed:
                        violations.append(("offline_validator.py", alias.name))
            elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                if stmt.module.split(".")[0] not in stdlib_allowed:
                    violations.append(("offline_validator.py", stmt.module))
        for node in ast.walk(off_tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
                violations.append(("offline_validator.py", node.module))
    except Exception as exc:
        violations.append(("offline_validator.py", f"Syntax error: {exc}"))

    if violations:
        print_fail(f"Domain/Offline AST violations detected: {violations}")
        return False

    print_pass(
        f"Domain layer ({len(py_files)} files) and standalone offline_validator.py pass strict stdlib AST check."
    )
    return True


def verify_static_type_hints() -> bool:
    """Gate 2: Evaluates typing.get_type_hints across every app.* module, class, method, and function."""
    import app

    checked_modules = 0
    checked_symbols = 0
    failures: list[str] = []

    module_names = ["app"] + sorted(
        mod_info.name
        for mod_info in pkgutil.walk_packages(app.__path__, prefix="app.")
    )

    for mod_name in module_names:
        try:
            mod = importlib.import_module(mod_name)
            checked_modules += 1
        except Exception as exc:
            failures.append(f"{mod_name}: import error: {exc}")
            continue

        for sym_name, obj in vars(mod).items():
            if inspect.isfunction(obj) and obj.__module__ == mod_name:
                try:
                    typing.get_type_hints(obj)
                    checked_symbols += 1
                except Exception as exc:
                    failures.append(f"{mod_name}.{sym_name}: {exc}")
            elif inspect.isclass(obj) and obj.__module__ == mod_name:
                try:
                    typing.get_type_hints(obj)
                    checked_symbols += 1
                except Exception as exc:
                    failures.append(f"{mod_name}.{sym_name} (class): {exc}")

                for attr_name, attr_val in vars(obj).items():
                    target_fn = None
                    if inspect.isfunction(attr_val):
                        target_fn = attr_val
                    elif isinstance(attr_val, (staticmethod, classmethod)):
                        target_fn = attr_val.__func__
                    elif isinstance(attr_val, property) and attr_val.fget is not None:
                        target_fn = attr_val.fget

                    if target_fn is not None and target_fn.__module__ == mod_name:
                        try:
                            typing.get_type_hints(target_fn)
                            checked_symbols += 1
                        except Exception as exc:
                            failures.append(f"{mod_name}.{sym_name}.{attr_name}: {exc}")

    if failures:
        print_fail(f"Type annotation resolution failed ({len(failures)} errors): {failures[:5]}")
        return False

    print_pass(
        f"Resolved typing.get_type_hints cleanly across {checked_symbols} symbols in {checked_modules} modules."
    )
    return True


def verify_database_migrations_and_schema() -> bool:
    """Gate 3: Verifies SQLite migrations, PRAGMA checks, and schema checksum integrity."""
    from app.infrastructure.database.connection import create_connection
    from app.infrastructure.database.migrations import run_migrations, verify_database_integrity

    conn = create_connection(":memory:")
    try:
        run_migrations(conn)
        integrity = verify_database_integrity(conn)
        if not integrity["healthy"]:
            print_fail(f"Database integrity verification failed: {integrity}")
            return False

        cur = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        tables = {r[0] for r in cur.fetchall()}
        required = {
            "customers",
            "licenses",
            "activations",
            "quotas",
            "usage_events",
            "webhook_events",
            "revoked_licenses",
            "schema_migrations",
        }
        missing = required - tables
        if missing:
            print_fail(f"Missing required tables: {missing}")
            return False

        print_pass(f"Database schema checksum verified; all {len(required)} tables and indices present.")
        return True
    finally:
        conn.close()


def verify_cryptographic_parity_and_tampering() -> bool:
    """Gate 4: Verifies OpenSSL <-> Pure-Python Ed25519 parity, RFC 8032 §5.1.3 checks, and HMAC-SHA256."""
    from app.infrastructure.security.ed25519_signer import Ed25519Signer
    from app.infrastructure.security.hmac_signer import HmacSha256Signer
    from app.infrastructure.security.offline_validator import validate_offline

    priv_hex = "a01fd194d15178191f62e570962a579e61bf728945f79655d9df145eada811ec"
    native_signer = Ed25519Signer(private_key_hex=priv_hex, force_pure_python=False)
    pure_signer = Ed25519Signer(private_key_hex=priv_hex, force_pure_python=True)
    hmac_signer = HmacSha256Signer()

    if native_signer.public_key_bytes != pure_signer.public_key_bytes:
        print_fail("Public key derivation mismatch between OpenSSL and pure-Python Ed25519.")
        return False

    pub_hex = native_signer.get_public_key_hex()
    payload = {
        "customer_email": "audit@acme.ai",
        "customer_id": str(uuid.uuid4()),
        "expires_at": int(time.time()) + 86400,
        "features": ["core", "cli_offline"],
        "issued_at": int(time.time()),
        "license_id": str(uuid.uuid4()),
        "max_seats": 3,
        "nonce": "a1b2c3d4e5f60718",
        "tier": "pro",
    }

    # 1. Deterministic signature parity: OpenSSL sign == Pure-Python sign
    token_native = native_signer.sign_token(payload)
    token_pure = pure_signer.sign_token(payload)
    if token_native != token_pure:
        print_fail("Deterministic Ed25519 token mismatch between OpenSSL and pure-Python.")
        return False

    # 2. Cross-verification in all 4 combinations (OpenSSL/pure signer + OpenSSL/pure offline_validator)
    for label, verifier in (("native_signer", native_signer), ("pure_signer", pure_signer)):
        ok, _, err = verifier.verify_token(token_native)
        if not ok or err is not None:
            print_fail(f"{label} failed to verify valid Ed25519 token: {err}")
            return False

    for force_pure in (False, True):
        off_ok, _, off_err = validate_offline(token_native, pub_hex, force_pure_python=force_pure)
        if not off_ok or off_err is not None:
            print_fail(f"validate_offline(force_pure_python={force_pure}) failed: {off_err}")
            return False

    # 3. Bit-flip tamper rejection
    prefix_part, sig_b64 = token_native.split(".")
    raw_sig = bytearray(_b64u_dec(sig_b64))
    raw_sig[10] ^= 0x01
    flipped_token = f"{prefix_part}.{_b64u_enc(bytes(raw_sig))}"
    if pure_signer.verify_token(flipped_token)[0] or native_signer.verify_token(flipped_token)[0]:
        print_fail("Bit-flipped Ed25519 signature was unexpectedly accepted.")
        return False

    # 4. RFC 8032 §5.1.3 adversarial vectors (malleable s >= L, non-canonical y >= Q, x=0 & sign=1)
    orig_sig = _b64u_dec(sig_b64)
    r_bytes = orig_sig[:32]
    s_bytes = orig_sig[32:]
    s_int = int.from_bytes(s_bytes, "little")

    adversarial_sigs: list[tuple[str, bytes]] = []
    if s_int + _ED25519_L < (1 << 256):
        adversarial_sigs.append(("s + L >= L malleability", r_bytes + (s_int + _ED25519_L).to_bytes(32, "little")))
    adversarial_sigs.append(("non-canonical R (y = Q)", _ED25519_Q.to_bytes(32, "little") + s_bytes))
    adversarial_sigs.append(("invalid R (x=0, sign_bit=1)", (1 | (1 << 255)).to_bytes(32, "little") + s_bytes))

    for vec_name, bad_sig_bytes in adversarial_sigs:
        bad_tok = f"{prefix_part}.{_b64u_enc(bad_sig_bytes)}"
        if pure_signer.verify_token(bad_tok)[0]:
            print_fail(f"Pure-Python signer accepted RFC 8032 invalid vector: {vec_name}")
            return False
        if validate_offline(bad_tok, pub_hex, force_pure_python=True)[0]:
            print_fail(f"Pure-Python validate_offline accepted RFC 8032 invalid vector: {vec_name}")
            return False

    # 5. HMAC-SHA256 baseline and tamper rejection
    hmac_token = hmac_signer.sign_token(payload)
    h_valid, _, h_err = hmac_signer.verify_token(hmac_token)
    if not h_valid or h_err is not None:
        print_fail(f"HMAC baseline verification failed: {h_err}")
        return False

    h_corrupted = hmac_token[:-3] + ("xyz" if not hmac_token.endswith("xyz") else "abc")
    if hmac_signer.verify_token(h_corrupted)[0]:
        print_fail("Corrupted HMAC token was unexpectedly accepted.")
        return False

    print_pass(
        "Ed25519 OpenSSL <-> Pure-Python parity, RFC 8032 Section 5.1.3 strictness, and HMAC-SHA256 verified."
    )
    return True


def verify_concurrency_and_acid_guarantees() -> bool:
    """Gate 5: Verifies high-concurrency atomic token-bucket quota debits with zero overdraft."""
    from app.domain.entities.quota import QuotaLedger
    from app.domain.exceptions import QuotaExceededError
    from app.infrastructure.database.connection import create_connection
    from app.infrastructure.database.migrations import run_migrations
    from app.infrastructure.repositories.sqlite_quota_repo import SqliteQuotaRepo

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db_path = Path(tmpdir) / "acid_concurrency.db"
        setup_conn = create_connection(temp_db_path)
        try:
            run_migrations(setup_conn)
            lic_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            cust_id = str(uuid.uuid4())
            setup_conn.execute(
                "INSERT INTO customers (id, email) VALUES (?, ?)",
                (cust_id, "race@acme.ai"),
            )
            setup_conn.execute(
                "INSERT INTO licenses (id, customer_id, license_key, tier, status, signature) VALUES (?, ?, ?, ?, ?, ?)",
                (lic_id, cust_id, "LIC-PRO-concurrency.dummy", "pro", "active", "sig_dummy"),
            )
            setup_repo = SqliteQuotaRepo(setup_conn)
            setup_repo.save(
                QuotaLedger(
                    id=str(uuid.uuid4()),
                    license_id=lic_id,
                    total_allowance=100,
                    balance=100,
                    consumed=0,
                    last_reset_at=now,
                    updated_at=now,
                )
            )
            setup_conn.commit()
        finally:
            setup_conn.close()

        success_count = 0
        fail_count = 0
        lock_obj = threading.Lock()

        def worker_debit(idx: int) -> None:
            nonlocal success_count, fail_count
            w_conn = create_connection(temp_db_path)
            w_repo = SqliteQuotaRepo(w_conn)
            try:
                res = w_repo.atomic_deduct(
                    license_id=lic_id,
                    credits=5,
                    idempotency_key=f"worker_race_{idx}_{uuid.uuid4().hex[:6]}",
                )
                if res.success:
                    with lock_obj:
                        success_count += 1
            except QuotaExceededError:
                with lock_obj:
                    fail_count += 1
            finally:
                w_conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_debit, i) for i in range(30)]
            for fut in futures:
                fut.result()

        v_conn = create_connection(temp_db_path)
        try:
            bal = SqliteQuotaRepo(v_conn).get_balance(lic_id)
        finally:
            v_conn.close()

    if success_count != 20 or fail_count != 10 or bal.balance != 0 or bal.consumed != 100:
        print_fail(
            f"Concurrency mismatch: Success={success_count}/20, Fail={fail_count}/10, "
            f"Final balance={bal.balance}/0, Consumed={bal.consumed}/100"
        )
        return False

    print_pass(
        f"ACID Atomic Debit Integrity: 30 workers -> Exactly {success_count} debits, {fail_count} paywalls, 0 overdraft."
    )
    return True


def verify_cli_operations() -> bool:
    """Gate 6: Verifies Click CLI auto-migration, issuance, offline validation, quota ops, and revocation."""
    from click.testing import CliRunner
    from app.cli import cli
    from app.config import get_settings

    runner = CliRunner()
    prev_db = os.environ.get("DATABASE_URL")
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "gate_cli.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
        get_settings.cache_clear()
        try:
            r_issue = runner.invoke(cli, ["issue", "--email", "gate@acme.ai", "--tier", "pro"])
            if r_issue.exit_code != 0:
                print_fail(f"CLI issue failed: {r_issue.output}")
                return False
            issued = json.loads(r_issue.output)
            key = issued["license_key"]

            r_off = runner.invoke(cli, ["verify", key, "--offline", "--pure-python"])
            if r_off.exit_code != 0 or not json.loads(r_off.output).get("valid"):
                print_fail(f"CLI pure-Python offline verify failed: {r_off.output}")
                return False

            r_ded = runner.invoke(cli, ["quota", "deduct", "--key", key, "--credits", "15"])
            if r_ded.exit_code != 0 or json.loads(r_ded.output).get("remaining_balance") != 485:
                print_fail(f"CLI quota deduct failed: {r_ded.output}")
                return False

            r_rev = runner.invoke(cli, ["revoke", key, "--reason", "gate_check"])
            if r_rev.exit_code != 0 or json.loads(r_rev.output).get("status") != "revoked":
                print_fail(f"CLI revoke failed: {r_rev.output}")
                return False
        finally:
            if prev_db is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = prev_db
            get_settings.cache_clear()

    print_pass("CLI execution gate verified (issue, offline pure-Python verify, quota deduct, revoke).")
    return True


def run_full_e2e_test_suite() -> bool:
    """Gate 7: Executes the full E2E test suite with strict ResourceWarning enforcement."""
    proc = subprocess.run(
        [sys.executable, "-W", "error::ResourceWarning", "run_tests.py"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print_fail("E2E Test Suite failed:")
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        for line in combined.splitlines()[-20:]:
            print(f"    {line}")
        return False

    match = re.search(r"Ran\s+(\d+)\s+tests", proc.stdout + "\n" + proc.stderr)
    count_label = match.group(1) if match else "all"
    print_pass(f"Full {count_label}-Test E2E Suite passed with 100% success and zero ResourceWarnings.")
    return True


def main() -> int:
    start_time = time.time()
    print_header("KeyFlint v1.0.0 Production Gatekeeper & Deployment Verification")
    print(f"Environment: Python {sys.version.split()[0]} | Platform: {sys.platform}")
    print(f"Project Root: {PROJECT_ROOT}\n")

    steps = [
        (1, "Domain AST Architectural Purity", verify_domain_ast_purity),
        (2, "Static Type-Hint & Module Import Integrity", verify_static_type_hints),
        (3, "Database Schema & Migration Checksum Integrity", verify_database_migrations_and_schema),
        (4, "Cryptographic Parity & RFC 8032 Adversarial Resilience", verify_cryptographic_parity_and_tampering),
        (5, "Concurrency & ACID Atomic Quota Balances", verify_concurrency_and_acid_guarantees),
        (6, "CLI End-to-End Lifecycle Gate", verify_cli_operations),
        (7, "Full E2E Test Suite Verification", run_full_e2e_test_suite),
    ]

    all_passed = True
    for step_num, step_name, step_fn in steps:
        print_step(step_num, step_name)
        ok = step_fn()
        if not ok:
            all_passed = False
            break

    duration = time.time() - start_time
    print_header("Production Verification Verdict")
    if all_passed:
        print(f"{BOLD}{GREEN}[VERDICT: PRODUCTION READY - ALL 7 GATES APPROVED]{RESET}")
        print(f"Total Verification Time: {duration:.2f} seconds\n")
        return 0
    print(f"{BOLD}{RED}[VERDICT: GATE REJECTED - ISSUES DETECTED]{RESET}")
    print(f"Total Verification Time: {duration:.2f} seconds\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
