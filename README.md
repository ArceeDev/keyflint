# KeyForge v1.1.0

**Cryptographic Licensing Gateway & Atomic Quota-Metering for AI Agents, MCP Servers, CLIs, and Micro-SaaS**

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](pyproject.toml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![Node.js >=18.4](https://img.shields.io/badge/node-%3E%3D18.4-brightgreen.svg)](https://nodejs.org/)
[![Server License: BSL 1.1](https://img.shields.io/badge/gateway%20license-BSL--1.1-orange.svg)](LICENSE)
[![SDK License: MIT](https://img.shields.io/badge/sdk%20license-MIT-green.svg)](sdks/js-verify/LICENSE)
[![Tests: 152/152 Pass](https://img.shields.io/badge/tests-152%2F152%20pass-brightgreen.svg)](run_tests.py)
[![Docker: GHCR](https://img.shields.io/badge/docker-ghcr.io%2Farceedev%2Fkeyforge%3A1.1.0-blue.svg)](https://github.com/ArceeDev/keyforge/pkgs/container/keyforge)

---

## Overview

**KeyForge** is a self-hosted licensing gateway and atomic usage-metering engine engineered for developers monetizing Model Context Protocol (MCP) servers, autonomous AI agents, developer CLIs, desktop applications, and vertical micro-SaaS.

Traditional licensing SaaS platforms (such as Keygen or Cryptolens) charge **$49 to $499 every month**, demand third-party dependency, and introduce blocking network hops on every tool invocation. KeyForge issues compact, tamper-proof **RFC 8032 Ed25519 signed tokens** (`LIC-<TIER>-<PAYLOAD>.<SIGNATURE>`) that client SDKs verify **100% offline in under 1 millisecond** with zero runtime network requirements.

For cloud operations and tool gating, KeyForge provides an embedded ACID quota engine backed by SQLite WAL with immediate serialization. When an agent or MCP client invokes a metered tool, KeyForge decrements usage atomically with zero overdraft risk under high concurrency, supports dynamic key rotation by `kid`, and includes a 900-second execution refund window if an downstream LLM call fails.

---

## Architecture & Guarantees

```text
┌────────────────────────────────────────────────────────────────────────┐
│                          KEYFORGE ARCHITECTURE                         │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  [Issuer / Billing Gateway]                                            │
│   ├── Stripe / LemonSqueezy HMAC-signed webhooks                       │
│   ├── Ed25519 Asymmetric Signer (RFC 8032 §5.1.3 + OpenSSL / pure-py) │
│   ├── Key ID ('kid') dynamic rotation & active signing ring            │
│   └── SQLite WAL Quota Ledger (BEGIN IMMEDIATE + ACID debit/refund)   │
│                                │                                       │
│                                ▼                                       │
│                   LIC-PRO-<PAYLOAD>.<SIGNATURE>                        │
│                                │                                       │
│          ┌─────────────────────┴─────────────────────┐                 │
│          ▼                                           ▼                 │
│  [Air-Gapped Offline Verify]              [Metered MCP Tool Execution] │
│   ├── Zero network calls                   ├── Offline signature check │
│   ├── Hardware seat fingerprint            ├── POST /quota/deduct      │
│   ├── Domain origin match                  │   (atomic SQLite WAL)     │
│   ├── Feature flag bitmask                 ├── Run downstream tool/LLM │
│   └── Execution time: < 1 ms               └── If tool throws error:   │
│                                                POST /quota/refund (900s)│
└────────────────────────────────────────────────────────────────────────┘
```

- **Asymmetric Security**: The Ed25519 private key never leaves your server. Clients possess only the 32-byte public key hex, making token forgery mathematically impossible.
- **Air-Gapped Speed (< 1 ms)**: Verification runs locally via the Web Crypto API (Node.js, Bun, Deno, browser) or Python standard library without C compiler dependencies.
- **ACID Quota Metering**: Zero race conditions or double-spending under concurrent loads via SQLite WAL `BEGIN IMMEDIATE` transactions and tenant-scoped `UNIQUE(license_id, idempotency_key)` deduplication.
- **MCP Auto-Refunds**: If a metered AI generation or tool handler fails after debiting credits, client wrappers automatically execute an atomic refund within a 900-second window.

---

## Quickstart

### 1. Run the Gateway Server (Docker)

Run the official container directly from GitHub Container Registry:

```bash
docker pull ghcr.io/arceedev/keyforge:1.1.0

docker run -d \
  --name keyforge \
  -p 8788:8788 \
  -v keyforge_data:/data \
  -e ENVIRONMENT=production \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e ADMIN_API_KEY=$(openssl rand -hex 24) \
  ghcr.io/arceedev/keyforge:1.1.0
```

- **Interactive Console & Live Verifier**: `http://127.0.0.1:8788`
- **OpenAPI Schema & Docs**: `http://127.0.0.1:8788/docs`
- **Health Probes**: `http://127.0.0.1:8788/healthz` and `http://127.0.0.1:8788/readyz`

---

## Client SDKs & MCP Integration

KeyForge provides zero-dependency, type-safe client SDKs for TypeScript and Python.

### TypeScript / JavaScript SDK (`keyforge-verify`)

```bash
# Direct from Release Asset:
npm install https://github.com/ArceeDev/keyforge/releases/download/v1.1.0/keyforge-verify-1.1.0.tgz

# Or via Git:
npm install git+https://github.com/ArceeDev/keyforge.git#subdirectory=sdks/js-verify
```

#### 1. Air-Gapped Offline Verification (< 1 ms)
```typescript
import { verifyLicense } from "keyforge-verify";

const result = await verifyLicense("LIC-PRO-eyJ...", PUBLIC_KEY_HEX, {
  machineId: "ws-node-01" // Optional: required only for node-locked licenses
});

if (!result.valid) {
  throw new Error(`License rejected: ${result.error}`);
}

console.log(`Tier: ${result.payload.tier}, Features:`, result.payload.features);
```

#### 2. Gating Model Context Protocol (MCP) Tools
```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { createKeyForge } from "keyforge-verify/mcp";
import { z } from "zod";

const server = new McpServer({ name: "ResearchAgent", version: "1.0.0" });
const kf = createKeyForge(); // Reads KEYFORGE_LICENSE, KEYFORGE_PUBLIC_KEYS, KEYFORGE_URL

// Feature-gated tool (100% offline check, zero network calls):
server.registerTool("code_review", { inputSchema: { repo: z.string() } },
  kf.requireLicense(async ({ repo }) => ({
    content: [{ type: "text", text: `Reviewing ${repo}` }]
  }, { features: ["premium"] })
);

// Quota-metered tool (atomic debit + auto-refund on handler failure):
server.registerTool("deep_research", { inputSchema: { query: z.string() } },
  kf.metered(5, async ({ query }) => {
    // Costs 5 credits. Automatically refunded if an exception is thrown here.
    return { content: [{ type: "text", text: `Results for: ${query}` }] };
  })
);
```

---

### Python SDK (`keyforge_verify`)

```bash
# Direct from Release Asset:
pip install https://github.com/ArceeDev/keyforge/releases/download/v1.1.0/keyforge_verify-1.1.0-py3-none-any.whl

# Or via Git:
pip install git+https://github.com/ArceeDev/keyforge.git#subdirectory=sdks/python-verify
```

#### 1. Air-Gapped Offline Verification
```python
from keyforge_verify import verify_license

res = verify_license("LIC-PRO-eyJ...", PUBLIC_KEY_HEX, machine_id="ws-node-01")
if not res:
    raise SystemExit(f"Access Denied: {res.error}")

print(f"Tier: {res.payload['tier']}, Allowed Features: {res.payload['features']}")
```

#### 2. Model Context Protocol (FastMCP) Integration
```python
from mcp.server.fastmcp import FastMCP
from keyforge_verify.mcp import KeyForge

mcp = FastMCP("DataExtractionAgent")
kf = KeyForge() # Reads KEYFORGE_LICENSE, KEYFORGE_PUBLIC_KEYS, KEYFORGE_URL

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

## Comparison: KeyForge vs. Hosted Licensing SaaS

| Feature | KeyForge (Self-Hosted) | Keygen.sh / Cryptolens | Stripe Metered Billing |
| :--- | :--- | :--- | :--- |
| **Pricing Model** | **One-time payment ($149 / $349)** | **$49 – $499 / month recurring** | 0.5% – 0.8% + monthly minimums |
| **Verification Speed** | **< 1 ms (Local Ed25519)** | ~150 – 400 ms (HTTP API call) | N/A (Billing only) |
| **Air-Gapped Offline Mode** | **Native (RFC 8032 standard-lib)** | Requires complex cached leasing | No (Requires active network) |
| **MCP Integration** | **Native `@metered` & auto-refund** | Manual custom code | Manual custom webhook polling |
| **Data Sovereignty** | **100% On-Premise / Your VPS** | Hosted US/EU SaaS servers | Third-party cloud |
| **Key Rotation** | **Zero-downtime `kid` ring** | Platform dependent | N/A |
| **Client Footprint** | **Zero third-party dependencies** | Heavy proprietary SDKs | Heavy HTTP SDKs |

---

## Production Verification & Test Suite

KeyForge enforces a mandatory 7-gate architectural verification suite prior to all releases.

```bash
# 1. Run the Gatekeeper Verification Suite (7 Gates)
python verify_production.py

# 2. Run the Full Backend E2E Suite (79 Tests)
python -W error::ResourceWarning run_tests.py

# 3. Run the TypeScript SDK Conformance Suite (57 Tests)
cd sdks/js-verify && npm test

# 4. Run the Python SDK Conformance Suite (16 Tests)
cd sdks/python-verify && python -m unittest discover -s tests
```

**Verification Status: 152 / 152 Tests Passing (100% Deterministic Approval)**.

---

## Licensing

KeyForge is distributed under a sustainable dual-license model:

1. **Client SDKs (`sdks/js-verify`, `sdks/python-verify`)**: Licensed under the permissive **[MIT License](sdks/js-verify/LICENSE)**. You can freely vendor, bundle, and distribute them with any commercial product.
2. **Server Gateway (`app/`)**: Licensed under the **[Business Source License 1.1 (BSL 1.1)](LICENSE)**.
   - **Free Use**: You may freely deploy and use the gateway for internal testing, development, education, and non-commercial evaluation.
   - **Commercial Production Use**: Commercial deployment in production requires an **Indie Developer License ($149 one-time)** or an **Agency/Studio License ($349 one-time)**.
   - **Open Source Transition**: Under the BSL 1.1 change date terms, the gateway code automatically converts to the open-source **Apache 2.0 License** on October 31, 2030.

---

## Commercial Distribution Kit

For complete commercial sales copy, objections handling, pricing breakdown, and marketing launch blueprints, refer to [COMMERCIAL_LAUNCH_KIT.md](COMMERCIAL_LAUNCH_KIT.md).
