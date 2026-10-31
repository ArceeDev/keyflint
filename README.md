# KeyForge v1.0.0

**Cryptographic Licensing & Atomic Quota-Metering Gateway for AI Tools, MCP Servers, CLIs, and Micro-SaaS**

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](pyproject.toml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests: 65/65 Pass](https://img.shields.io/badge/tests-65%2F65%20pass-brightgreen.svg)](run_tests.py)

---

## Overview

**KeyForge** is a self-hosted licensing and usage-metering gateway built for software creators shipping paid AI agents, Model Context Protocol (MCP) servers, developer CLIs, desktop software, and vertical APIs.

Hosted licensing platforms charge recurring revenue shares or require continuous internet connectivity. KeyForge issues compact **RFC 8032 Ed25519 signed tokens** (`LIC-<TIER>-<PAYLOAD>.<SIGNATURE>`) verifiable either **online** (with hardware seat locks, domain locks, revocation ledgers, and atomic credit debits) or **100% air-gapped offline** using a single zero-dependency Python standard-library module (`app/infrastructure/security/offline_validator.py`) or browser WebCrypto.

---

## Core Capabilities

- **Dual Cryptographic Engine (Ed25519 + HMAC-SHA256)**:
  - Native OpenSSL Ed25519 signing/verification paired with an optimized extended twisted Edwards `(X, Y, Z, T)` pure-Python fallback enforcing strict RFC 8032 Section 5.1.3 checks (`s < L`, canonical `y < p`, curve membership, and `x = 0` sign rejection).
  - Zero third-party packages required on client machines for offline token verification.
- **Hardware Node & Wildcard Domain Locking**:
  - Case-normalized hardware fingerprint seat limits (`max_seats`) and optional exact or `*.domain.tld` origin restrictions.
- **ACID Token-Bucket Quota Metering**:
  - SQLite WAL persistence with `BEGIN IMMEDIATE` serialization, automatic `SQLITE_BUSY` jitter backoff, tenant-scoped `UNIQUE(license_id, idempotency_key)` deduplication, and HTTP `402 Payment Required` paywall triggers with zero overdraft under concurrency.
- **Stripe & LemonSqueezy Billing Webhooks**:
  - Constant-time HMAC verification (including multi-`v1=` Stripe secret rotation and native LemonSqueezy `meta.event_name` / `data.attributes` ingestion), replay deduplication, grace-period headers (`X-Subscription-Warning`), non-inflating cycle renewals, and automatic token re-signing on tier upgrades.
- **Production Hardening & Interactive Console**:
  - Pure-ASGI `SecurityHeadersMiddleware` (CSP, HSTS, synced `X-Request-ID`), streaming-aware `PayloadSizeLimitMiddleware` (64 KB), spoof-resistant sliding-window `RateLimitMiddleware`, `X-Admin-Key` enforcement, production secret fail-fast startup validation, and an integrated B2B dark web console at `/`.

---

## Quickstart

### 1. Install Dependencies

```powershell
cd C:\Users\Usuario\teamwork_projects\monetizable_project
pip install -r requirements.txt
```

### 2. Run the 7-Gate Production Verification Suite

```powershell
python verify_production.py
```

Expected verdict:

```text
[STEP 1] Domain AST Architectural Purity... [PASS]
[STEP 2] Static Type-Hint & Module Import Integrity... [PASS]
[STEP 3] Database Schema & Migration Checksum Integrity... [PASS]
[STEP 4] Cryptographic Parity & RFC 8032 Adversarial Resilience... [PASS]
[STEP 5] Concurrency & ACID Atomic Quota Balances... [PASS]
[STEP 6] CLI End-to-End Lifecycle Gate... [PASS]
[STEP 7] Full E2E Test Suite Verification... [PASS]
[VERDICT: PRODUCTION READY - ALL 7 GATES APPROVED]
```

### 3. Run the E2E Test Suite Directly

```powershell
python -W error::ResourceWarning run_tests.py
```

### 4. Start the Gateway Server

```powershell
python -m app.cli serve --host 127.0.0.1 --port 8000
```

- Interactive Console & Offline WebCrypto Validator: `http://127.0.0.1:8000`
- OpenAPI Specification: `http://127.0.0.1:8000/docs`
- Health & Readiness Probes: `http://127.0.0.1:8000/healthz` and `http://127.0.0.1:8000/readyz`

---

## CLI Usage

`app.cli` automatically initializes and migrates the configured SQLite database on first run:

```powershell
# Issue a Pro license (applies tier defaults: 3 seats, 500 credits, 365 days)
python -m app.cli issue --email "alex@acme.ai" --tier "pro"

# Verify offline using pure-Python RFC 8032 math (zero network calls)
python -m app.cli verify "LIC-PRO-..." --offline --pure-python

# Bind a workstation hardware fingerprint
python -m app.cli activate "LIC-PRO-..." --hardware-id "ws-node-01" --machine-name "dev-laptop"

# Inspect balance, deduct credits idempotently, and top up quota
python -m app.cli quota balance "LIC-PRO-..."
python -m app.cli quota deduct "LIC-PRO-..." --credits 10 --idempotency-key "job-001"
python -m app.cli quota replenish "LIC-PRO-..." --credits 100

# Revoke a license immediately
python -m app.cli revoke "LIC-PRO-..." --reason "subscription_cancelled"
```

---

## Zero-Dependency Air-Gapped Client Verification

Vendor `app/infrastructure/security/offline_validator.py` directly into any Python CLI, agent, or desktop app:

```python
from app.infrastructure.security.offline_validator import validate_offline

is_valid, payload, error_code = validate_offline(
    license_token="LIC-PRO-...",
    public_key_hex="0043b567534bfa2d55059a05642f75573d420899146f334a9f7fc5fba797bd0b",
    expected_machine_id="ws-node-01",
)

if is_valid:
    print(payload["tier"], payload["features"])
else:
    print("Rejected:", error_code)
```

---

## Architecture & Production Deployment

- `app/domain/`: Pure Python standard-library domain entities (`Customer`, `License`, `Activation`, `QuotaLedger`), repository/signer ports, and domain exceptions.
- `app/application/`: Use-case services (`LicenseService`, `QuotaService`, `BillingService`) and Pydantic v2 DTOs.
- `app/infrastructure/`: SQLite WAL connection factory & migrations, repositories, Ed25519/HMAC signers, standalone offline validator, and structured logging.
- `app/presentation/`: FastAPI v1 routers, pure-ASGI security/payload/rate-limit middlewares, RFC 7807 error handlers, and static web console.

Before deploying with `ENVIRONMENT=production`, copy `.env.example` to `.env` and replace `SECRET_KEY`, `ED25519_PRIVATE_KEY_HEX`, `ED25519_PUBLIC_KEY_HEX`, `ADMIN_API_KEY`, `STRIPE_WEBHOOK_SECRET`, and `LEMONSQUEEZY_WEBHOOK_SECRET`. Startup intentionally aborts if any default secret remains active in production, requires `X-Admin-Key` on administrative mutations (`/issue`, `/revoke`, `/quota/replenish`), and disables `/api/v1/billing/simulate-webhook`.

For full Spanish operational documentation, monetization strategy, and multi-session Argon handoff checkpoints, see [ARGON_SESSION_GUIDE.md](ARGON_SESSION_GUIDE.md).

---

## License

Released under the [MIT License](LICENSE).
