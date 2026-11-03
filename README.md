# KeyFlint v1.1.0

Self-hosted license issuing and credit metering for MCP servers, CLIs and desktop apps.
The gateway signs Ed25519 license tokens; your code verifies them offline with a 32-byte
public key and debits credits with one HTTP call per metered tool.

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](pyproject.toml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![Node.js >=18.4](https://img.shields.io/badge/node-%3E%3D18.4-brightgreen.svg)](https://nodejs.org/)
[![Server License: BSL 1.1](https://img.shields.io/badge/gateway%20license-BSL--1.1-orange.svg)](LICENSE)
[![SDK License: MIT](https://img.shields.io/badge/sdk%20license-MIT-green.svg)](sdks/js-verify/LICENSE)
[![CI](https://github.com/ArceeDev/keyflint/actions/workflows/ci.yml/badge.svg)](https://github.com/ArceeDev/keyflint/actions/workflows/ci.yml)
[![Docker: GHCR](https://img.shields.io/badge/docker-ghcr.io%2Farceedev%2Fkeyflint%3A1.1.0-blue.svg)](https://github.com/ArceeDev/keyflint/pkgs/container/keyflint)

---

## Quickstart

### 1. Start the gateway (Universal: Windows, macOS, Linux)

```bash
# 1. Initialize production environment in 1 second (generates Ed25519 keypair and secrets):
python -m app.cli init --env production

# 2. Run the gateway container:
docker run -d --name keyflint -p 8000:8000 -v keyflint_data:/app/data \
  --env-file .env ghcr.io/arceedev/keyflint:1.1.0
# (Or run natively: python -m app.cli serve --host 0.0.0.0 --port 8000)

# 3. Check readiness probe:
curl -s localhost:8000/readyz
```

*For headless Linux servers without local Python, you can write the `.env` directly:*
<details>
<summary>Linux Bash heredoc alternative</summary>

```bash
cat > .env <<EOF
ENVIRONMENT=production
SECRET_KEY=$(openssl rand -hex 32)
ADMIN_API_KEY=kf_$(openssl rand -hex 24)
ED25519_PRIVATE_KEY_HEX=$(openssl rand -hex 32)
ED25519_PUBLIC_KEY_HEX=
STRIPE_WEBHOOK_SECRET=whsec_$(openssl rand -hex 24)
LEMONSQUEEZY_WEBHOOK_SECRET=$(openssl rand -hex 24)
EOF

docker run -d --name keyflint -p 8000:8000 -v keyflint_data:/app/data \
  --env-file .env ghcr.io/arceedev/keyflint:1.1.0
```
</details>

`ED25519_PUBLIC_KEY_HEX` is derived automatically from the private key if left empty. Back up your `.env`: without `ED25519_PRIVATE_KEY_HEX` you cannot issue tokens that existing clients accept.

Console: `http://127.0.0.1:8000` · OpenAPI: `/docs` · Probes: `/healthz`, `/readyz`

### 2. Issue a license and fetch the public key

```bash
# Issue an official Pro license directly via CLI:
python -m app.cli issue --email "dev@example.com" --tier "pro"

# Or via REST API:
ADMIN=$(python -c "import os; from app.config import get_settings; print(get_settings().ADMIN_API_KEY)")
curl -s -X POST localhost:8000/api/v1/licenses/issue \
  -H "X-Admin-Key: $ADMIN" -H "Content-Type: application/json" \
  -d '{"customer_email":"dev@example.com","tier":"pro","features":["premium"]}'
```

### 3. Protect an MCP tool (TypeScript & Python)

**TypeScript / Node.js:**
```bash
npm install keyflint-verify
export KEYFLINT_LICENSE=LIC-PRO-...  KEYFLINT_PUBLIC_KEYS=<keyring>  KEYFLINT_URL=http://localhost:8000
```

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { createKeyFlint } from "keyflint-verify/mcp";
import { z } from "zod";

const server = new McpServer({ name: "research", version: "1.0.0" });
const kf = createKeyFlint(); // KEYFLINT_LICENSE, KEYFLINT_PUBLIC_KEYS, KEYFLINT_URL

// Offline check only. Rejects licenses without the "premium" feature.
server.registerTool("code_review", { inputSchema: { repo: z.string() } },
  kf.requireLicense(
    async ({ repo }) => ({ content: [{ type: "text", text: `Reviewing ${repo}` }] }),
    { features: ["premium"] },
  ),
);

// Debits 5 credits before running; refunds them if the handler throws or returns isError.
server.registerTool("deep_research", { inputSchema: { query: z.string() } },
  kf.metered(5, async ({ query }) => ({ content: [{ type: "text", text: `Results for ${query}` }] })),
);
```

Python (FastMCP) uses the same environment variables: see [Python SDK](#python-sdk-keyflint_verify).

### What is enforced where

| Check | Where it runs | Network |
| :--- | :--- | :--- |
| Signature, expiry, issued_at, tier, features, machine/domain lock | Your process (`keyflint-verify`) | None |
| Credit debit / refund | Gateway (`/api/v1/quota/*`) | 1 request per call |

Metering is enforceable only when the metered tool runs on infrastructure you control (for example a
remote MCP server). If the MCP server runs on the customer's machine, the customer can remove the
`deduct` call; use licensing (features, expiry) for that case. Refunds are accepted for 900 s after a
deduct (`QUOTA_REFUND_WINDOW_SECONDS`, `0` disables them). A refunded idempotency key cannot be
deducted again (HTTP 409, `KEY_REFUNDED`).

**Refund circuit breaker (v1.2).** Refunds are requested by the SDK, which runs on the customer's
machine, so a modified client could refund successful calls. Per license, the gateway answers
`429 REFUND_VELOCITY_EXCEEDED` (credits stay charged) when more than 5 refunds in a row happen within
10 minutes, or refunds exceed 25 % of the last 50 deducts (once 10 exist). Each trip is stored in
`license_events` for manual review. Tune with `REFUND_BREAKER_*` or set `REFUND_BREAKER_ENABLED=false`.

**Client IP behind proxies (v1.2).** Rate limits key on the client IP. Set `TRUSTED_PROXY_MODE`:

| Mode | Client IP from | Use it for |
| :--- | :--- | :--- |
| `direct` (default) | TCP peer | Exposed directly; logs a warning when proxy headers show up |
| `fly` | `Fly-Client-IP` | Fly.io (`TRUST_PROXY_HEADERS=true` still means this) |
| `cloudflare` | `CF-Connecting-IP`, only from `TRUSTED_PROXY_IPS` | Cloudflare in front of your origin |
| `standard` | `X-Forwarded-For` (right-most untrusted hop) / `X-Real-IP`, only from `TRUSTED_PROXY_IPS` | nginx, Traefik, Caddy, Render, Railway |

`TRUSTED_PROXY_IPS` takes IPs/CIDRs of your own proxies; empty means loopback and private ranges.
Headers from any other peer are ignored, so they cannot be spoofed. For `cloudflare`, list
[Cloudflare's ranges](https://www.cloudflare.com/ips/) when the origin is reachable from the internet.

**Seats in containers (v1.2).** `POST /api/v1/licenses/nodes` lists the machines on a license and
`POST /api/v1/licenses/nodes/release` (`license_key`, `hardware_id`) frees one, at most once per 24 h
per license (`NODE_RELEASES_PER_24H`, `0` disables it), so a rebuilt container or devcontainer does
not need a support ticket. In the Python SDK, `KEYFLINT_MACHINE_ID_STRATEGY=stable` derives the id
from the host (Windows MachineGuid, macOS IOPlatformUUID, Linux/WSL `/etc/machine-id`,
`CODESPACE_NAME`, or `KEYFLINT_HOST_ID`), so rebuilds keep the same id; in Docker mount
`-v /etc/machine-id:/etc/machine-id:ro`. The default stays the v1.0 formula because node-locked
licenses embed it. Node.js: `stableMachineId()` from `keyflint-verify/mcp`.

**One-command activation for your customers (v1.2).** `npx keyflint-verify activate LIC-...` or
`uvx keyflint-verify activate LIC-...` writes the license into Claude Desktop, Cursor or Windsurf
(`--client`, `--server NAME`), with a `.bak` copy and a JSON validity check.

**Gateway blips (v1.2, opt-in).** `@kf.metered(credits=2, offline_grace_calls=3, timeout_ms=1500)`
(TS: `kf.metered(2, handler, { offlineGraceCalls: 3, timeoutMs: 1500 })`) lets up to N calls run
while the gateway is unreachable or answers 502/503/504, as long as the license verifies offline.
Their debits are queued in memory and replayed with the same idempotency key before the next
successful debit. Default 0 (fail closed), hard cap 5 per instance; queued debits are never
refunded, a replay the gateway refuses (402) is dropped, and the queue is lost if the process exits.

**Database maintenance (v1.2).** An hourly job (`MAINTENANCE_INTERVAL_SECONDS`, `0` disables it)
runs `PRAGMA wal_checkpoint(TRUNCATE)` when Litestream is not replicating (Litestream manages its
own checkpoints). `usage_events` is both the idempotency ledger and the usage history, so it is kept
forever unless you set `USAGE_EVENTS_RETENTION_DAYS` (minimum 30; deleted in batches of 5,000).
The redundant `idx_usage_idempotency` index (a duplicate of the UNIQUE key) is dropped on boot.

**Clock rollback (v1.2, SDKs).** For licenses with `expires_at`, the MCP wrappers remember the latest
time seen in `~/.keyflint/clock_state` (memory only if read-only; `KEYFLINT_CLOCK_STATE=off` keeps it
in memory) and reject a clock more than 300 s behind it with `ERR_CLOCK_ROLLBACK_DETECTED`. This is a
deterrent, not a guarantee: whoever controls the machine can delete the file, and a new container
starts without state. The low-level APIs take it as `last_seen` / `lastSeen` / `Options.LastSeen`.

---

## Deploy in one click

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ArceeDev/keyflint)
[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=https%3A%2F%2Fgithub.com%2FArceeDev%2Fkeyflint)

No secrets to prepare: on first boot the image generates the Ed25519 signing key, `SECRET_KEY`,
`ADMIN_API_KEY` and placeholder webhook secrets into `/app/data/secrets.env` (mode 600) and prints
the **public key** and the **admin key** once in the logs. Anything you set as an environment
variable wins over the generated value. Set `KEYFLINT_AUTO_SECRETS=0` to disable this.

| Platform | Config | Notes |
|---|---|---|
| Render | `render.yaml` | Disks need a paid instance (starter+). `SECRET_KEY`/`ADMIN_API_KEY` are generated by Render. |
| Railway | `railway.json` | In the template add a volume at `/app/data`, `ENVIRONMENT=production`, `DATABASE_URL=sqlite:////app/data/keyflint.db`. |
| Fly.io | `fly.toml` | `fly volumes create keyflint_data --size 1`, then `fly deploy`. |
| Docker | `docker-compose.yml` | `docker compose up -d`; secrets are optional. |

> **The data volume holds your signing key.** Without a persistent volume a redeploy creates a new
> key and every issued license stops verifying. Back the volume up. SQLite means exactly **one**
> instance: never scale horizontally.

Then set `STRIPE_WEBHOOK_SECRET` / `LEMONSQUEEZY_WEBHOOK_SECRET` to your provider's values before
taking payments (the placeholders reject every webhook). `python scripts/e2e_container.py` verifies
this whole path against a real container.

**Continuous backup (optional, recommended).** Set `LITESTREAM_BUCKET`, `LITESTREAM_ACCESS_KEY_ID`,
`LITESTREAM_SECRET_ACCESS_KEY` (and `LITESTREAM_ENDPOINT` for R2/MinIO, `LITESTREAM_PATH` for the
prefix). The database is replicated every second; on a fresh volume it is restored before the
gateway starts, and if the restore fails the container refuses to start. Litestream backs up the
database only: keep your secrets as environment variables (not only in `secrets.env`) so a lost
volume comes back with the same signing key. `python scripts/e2e_backup.py` verifies the recovery;
[`docs/ops/RESTORE_DRILL.md`](docs/ops/RESTORE_DRILL.md) runs the same check against production.
Hosting customers yourself: see [`scripts/managed/README.md`](scripts/managed/README.md).

## Architecture

```text
[Gateway]  Stripe / LemonSqueezy HMAC webhooks
           Ed25519 signer (RFC 8032; OpenSSL or pure Python) with kid key ring
           SQLite WAL quota ledger (BEGIN IMMEDIATE debit / refund)
               |
               v   LIC-PRO-<PAYLOAD>.<SIGNATURE>
               |
   +-----------+------------------------+
   v                                    v
[Offline verify]                  [Metered MCP tool]
 signature, expiry, issued_at      offline check
 machine lock, domain lock         POST /quota/deduct
 features                          run tool; on error POST /quota/refund
```

- **Signatures**: the private key stays on the gateway. Forging a token requires it (Ed25519, ~128-bit security level).
- **Verification cost**: about 0.13 ms with OpenSSL (`cryptography`) or Web Crypto; about 3 ms in pure Python. No network call.
- **Credit debits**: each debit is one conditional `UPDATE … WHERE balance >= ?` inside `BEGIN IMMEDIATE`, so the balance never goes negative on a single SQLite file. Replays with the same key are deduplicated by `UNIQUE(license_id, idempotency_key)`.
- **Refunds**: the SDK wrappers call `POST /quota/refund` once (best effort, no retry) when the handler throws or returns `isError`.
- **Key rotation**: a token with `kid` verifies only against the key with that `kid`; tokens without `kid` (v1.0) verify against every key in the ring. To contain a leaked key, remove it from the ring.
- **Clock**: tokens whose signed `issued_at` is more than 300 s ahead of the local clock fail with `ERR_CLOCK_BEFORE_ISSUANCE`. Offline checks cannot stop a determined clock rollback; use short expirations with online renewal when that matters.

---

## Client SDKs

All three SDKs (TypeScript, Python, Go) have no runtime dependencies (Python uses `cryptography` when
installed, for speed). Get the gateway public key from `GET /api/v1/licenses/public-key` (or the keyring
with `kid`s for rotation); it is also in every license email.

### TypeScript / JavaScript SDK (`keyflint-verify`)

```bash
npm install keyflint-verify
```

```typescript
import { verifyLicense } from "keyflint-verify";

const result = await verifyLicense("LIC-PRO-eyJ...", PUBLIC_KEYS);
if (!result.valid) throw new Error(`License rejected: ${result.error}`);
console.log(`Tier: ${result.payload.tier}, Features:`, result.payload.features);
```

Pass `{ machineId }` only for node-locked licenses; passing it for a floating license returns `ERR_NODE_LOCK_VIOLATION`.

MCP errors use the JSON-RPC codes `-32060` invalid license, `-32061` feature not in plan, `-32062` credits exhausted, `-32063` gateway error (`-32042` is reserved by MCP). MCP clients show the message text, so each message states the cause, whether credits were charged, and the next step (with `KEYFLINT_CHECKOUT_URL` when set).

---

### Python SDK (`keyflint-verify`)

```bash
pip install keyflint-verify
# Or with high-performance OpenSSL acceleration:
pip install "keyflint-verify[fast]"
```

#### 1. Air-Gapped Offline Verification
```python
from keyflint_verify import verify_license

res = verify_license("LIC-PRO-eyJ...", PUBLIC_KEYS)  # machine_id=... only for node-locked licenses
if not res:
    raise SystemExit(f"Access Denied: {res.error}")

print(f"Tier: {res.payload['tier']}, Allowed Features: {res.payload['features']}")
```

#### 2. Model Context Protocol (FastMCP) Integration
```python
from mcp.server.fastmcp import FastMCP
from keyflint_verify.mcp import KeyFlint

mcp = FastMCP("DataExtractionAgent")
kf = KeyFlint() # Reads KEYFLINT_LICENSE, KEYFLINT_PUBLIC_KEYS, KEYFLINT_URL

@mcp.tool()
@kf.require_license(features=["pro"])
def extract_entities(text: str) -> str:
    """Offline gated: rejects unauthorized execution with standard MCP error."""
    return f"Extracted entities from {text}"

@mcp.tool()
@kf.metered(credits=10)
async def analyze_document(url: str) -> str:
    """Atomically debits 10 credits. Auto-refunds if extraction crashes."""
    return f"Analysis complete for {url}"
```

---

### Go SDK (`go-verify`)

```bash
go get github.com/ArceeDev/keyflint/sdks/go-verify@v1.1.0   # Go 1.20+
```

```go
import keyflint "github.com/ArceeDev/keyflint/sdks/go-verify"

payload, err := keyflint.Verify(os.Getenv("KEYFLINT_LICENSE"), publicKeyHex)
if err != nil {
    log.Fatalf("license rejected: %s", keyflint.Code(err))
}
fmt.Println("tier:", payload.Tier)
```

Use `VerifyWithKeyRing` during key rotation and `VerifyWithOptions` for node-locked or domain-locked
licenses. Full reference: [`sdks/go-verify/README.md`](sdks/go-verify/README.md).

---

## Pricing

Prices in USD, VAT added at checkout. Buy at [keyflint.dev](https://keyflint.dev/#pricing-section).

| Plan | Price | Credits | Seats | License |
| :--- | :--- | :--- | :--- | :--- |
| Community | Free | 25 | 1 | Evaluation and non-commercial use |
| Indie | $149 one-time | 10,000 | 3 | Perpetual |
| Agency | $349 one-time | 50,000 | 25 | Perpetual |
| Pro Cloud | $29 / month | 500 per cycle | 3 | Renews monthly |
| Studio Cloud | $89 / month | 5,000 per cycle | 25 | Renews monthly |

Refunds within 14 days revoke the license automatically. Support: see [SUPPORT.md](SUPPORT.md).

---

## Comparison: KeyFlint vs. Hosted Licensing SaaS

| Feature | KeyFlint (Self-Hosted) | Keygen.sh / Cryptolens | Stripe Metered Billing |
| :--- | :--- | :--- | :--- |
| **Pricing Model** | **One-time ($149 / $349) or monthly ($29 / $89)** | Monthly subscription | Per-usage fee |
| **Verification** | **Local Ed25519, ~0.13 ms (OpenSSL)** | HTTP API call (offline mode varies by plan) | N/A (billing only) |
| **Offline Mode** | **Native (RFC 8032, standard library)** | Cached / leased validation | No |
| **MCP Integration** | **Native `@metered` & auto-refund** | Manual custom code | Manual custom webhook polling |
| **Data Sovereignty** | **Your server** | Hosted US/EU SaaS servers | Third-party cloud |
| **Key Rotation** | **Zero-downtime `kid` ring** | Platform dependent | N/A |
| **Client Runtime Dependencies** | **None** | Vendor SDK | Vendor SDK |

---

## Production Verification & Test Suite

Every release runs `verify_production.py` (7 gates) and the three test suites below.

```bash
# 1. Run the Gatekeeper Verification Suite (7 Gates)
python verify_production.py

# 2. Run the Full Backend E2E Suite
python -W error::ResourceWarning run_tests.py

# 3. Run the TypeScript SDK Conformance Suite (shared vectors in sdks/vectors)
cd sdks/js-verify && npm test

# 4. Run the Python SDK Conformance Suite
cd sdks/python-verify && PYTHONPATH=src python -m unittest discover -s tests

# 5. Run the Go SDK Conformance Suite
cd sdks/go-verify && go test ./...
```

**Status:** see the CI badge; a release requires every suite and all 7 gates green.

---

## Licensing

KeyFlint uses two licenses:

1. **Client SDKs (`sdks/js-verify`, `sdks/python-verify`, `sdks/go-verify`)**: Licensed under the permissive **[MIT License](sdks/js-verify/LICENSE)**. You can freely vendor, bundle, and distribute them with any commercial product.
2. **Server Gateway (`app/`)**: Licensed under the **[Business Source License 1.1 (BSL 1.1)](LICENSE)**.
   - **Free Use**: You may freely deploy and use the gateway for internal testing, development, education, and non-commercial evaluation.
   - **Commercial Production Use**: Commercial deployment in production requires a paid plan: **Indie ($149 one-time)**, **Agency ($349 one-time)**, **Pro Cloud ($29/month)** or **Studio Cloud ($89/month)**. See [Pricing](#pricing).
   - **Open Source Transition**: Under the BSL 1.1 change date terms, the gateway code automatically converts to the open-source **Apache 2.0 License** on October 31, 2030.

---

## Documentation, Operations & Legal Directory

### Commercial & Go-To-Market
- **[Commercial Launch Kit](docs/commercial/COMMERCIAL_LAUNCH_KIT.md)**: GTM positioning, pricing tiers, objections handling, and launch copy for Hacker News and X.
- **[MCP Prospect Leads](docs/commercial/MCP_PROSPECT_LEADS.md)**: 20 curated active Model Context Protocol repositories with tailored developer outreach copy.
- **[Sales Engine Automation](docs/commercial/SALES_ENGINE_AUTOMATION.md)**: Stripe Merchant of Record lifecycle and payment link webhooks.

### Infrastructure & Operations
- **[Cloudflare R2 & Fly.io Setup Guide](docs/ops/R2_FLY_SETUP.md)**: Private EU R2 bucket configuration, S3 token provisioning, and Fly.io deployment runbook.
- **[KeyFlint Managed Provisioning CLI](scripts/managed/README.md)**: Isolated single-tenant customer management and continuous Litestream replication.
- **[Distribution & Release Commands](docs/ops/DISTRIBUTION_COMMANDS.md)**: Publishing SDK packages to npm, PyPI, and GitHub Container Registry.

### Legal & Compliance (EU GDPR)
- **[Data Processing Agreement (DPA Borrador)](docs/legal/DPA_BORRADOR.md)**: Article 28 GDPR compliant data processing terms for KeyFlint Managed.
- **[Privacy Policy (Privacidad Borrador)](docs/legal/PRIVACIDAD_BORRADOR.md)**: Privacy policy tailored to Stripe Merchant of Record and EU data retention rules.
