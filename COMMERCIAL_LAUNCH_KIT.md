# KeyForge — Commercial Launch & Distribution Kit (Zero-Slop Edition)

> **Objective**: Monetize KeyForge immediately with zero corporate fluff or AI clichés. This document contains battle-tested sales copy, technical positioning, developer objection handling, launch templates, and the exact go-to-market playbook.

---

## 1. Grounded Technical Positioning

### The Problem
If you build a paid developer CLI, Model Context Protocol (MCP) server, local AI tool, or desktop app, licensing is a nightmare:
1. **Hosted Licensing SaaS is Expensive**: Services like Keygen.sh or Cryptolens charge **$49 to $499 every single month**, eating your margin before you even validate product-market fit.
2. **Platform Keys are Fragile**: Gumroad/Whop license keys require an HTTP ping on every run. If the user is on an airplane, in a secure corporate network, or the platform API is slow, your tool hangs.
3. **Custom Solutions Have Bugs**: Rolling your own crypto verification usually ends up with signature malleability issues, race conditions during credit debits, or requiring heavy C dependencies that break across client OS platforms.

### The KeyForge Value Proposition
- **Self-Hosted & Zero Royalty**: Runs as a single Docker container (`ghcr.io/arceedev/keyforge:1.1.0`) or Python process on a $5/mo VPS. No revenue share, no third-party lock-in.
- **Asymmetric Ed25519 (RFC 8032)**: Private key stays on your server. Clients verify offline using a **zero-dependency package** (`keyforge-verify` for TS or Python) in `< 1 ms`.
- **Atomic Credit Quota (SQLite WAL)**: High-speed credit metering using `BEGIN IMMEDIATE` transactions with zero overdraft under heavy multi-threaded concurrency.
- **Native MCP Wrappers**: `@metered` decorators for FastMCP and `@modelcontextprotocol/sdk` with automatic 900s execution refunds if the downstream model fails.
- **Native Stripe & LemonSqueezy Webhooks**: Automatic provisioning, renewals, grace periods, and tier upgrades.

---

## 2. Technical Developer Objections & Defenses

### Objection 1: *"Why not just use standard JWTs with HMAC-SHA256?"*
**The Defense**:
HMAC is symmetric: the same secret key that verifies the token can also create new tokens. If you ship an HMAC secret to client applications, any developer with a debugger can extract that secret and forge valid enterprise tokens indefinitely.
KeyForge uses **Ed25519 asymmetric cryptography**. Your private signing key never leaves your production server. Clients only receive the 32-byte public key hex. Even with full decompilation and reverse-engineering, a client can only verify tokens, never mint them. Furthermore, KeyForge rejects algorithm confusion attacks (`none`, HS256) by enforcing fixed RFC 8032 curve verification.

### Objection 2: *"What stops a client from freezing or rewinding their system clock to bypass expiration?"*
**The Defense**:
KeyForge designs offline tokens for air-gapped convenience, not infinite disconnected usage. 
1. Tokens contain signed `exp` (UNIX expiration timestamp).
2. For high-assurance desktop applications, client SDKs support periodic heartbeats or monotonic timestamp checks against local files.
3. For tools that consume LLM tokens or external compute, the tool must invoke the gateway for quota debits (`/quota/deduct`), which relies on server-authoritative time regardless of client clock manipulation.

### Objection 3: *"What if an upstream AI model (Claude/OpenAI) crashes mid-request after credits were debited?"*
**The Defense**:
KeyForge provides an automatic **900-second execution refund window**.
When an MCP tool wrapped with `@metered` debits quota, it generates an atomic `idempotency_key`. If the downstream tool handler raises an exception, the client wrapper automatically sends a `POST /api/v1/quota/refund` request with the same transaction ID. KeyForge credits the exact amount back to the customer's balance without double-crediting.

---

## 3. Ready-to-Paste LemonSqueezy / Gumroad Product Listing

### Product Title
**KeyForge — Self-Hosted Ed25519 Licensing & Quota-Metering Gateway**

### Subtitle
*Stop paying $50–$200/month to licensing SaaS. Ship offline-verifiable software licenses and atomic API credit quotas for MCP servers and CLIs from your own $5 VPS.*

### Body Description

```markdown
Building a paid CLI, AI agent, Model Context Protocol (MCP) server, or developer tool?

You shouldn't have to pay $600/year to Keygen or give up 10% of your revenue to a closed marketplace just to verify license keys and meter usage.

**KeyForge** is a production-grade, self-hosted licensing and credit-metering gateway that runs on your own server and verifies in milliseconds without external dependencies.

### What You Get:
1. **Complete Gateway Source Code**: Hardened FastAPI backend (Python 3.12+) with Clean Architecture and strict static typing.
2. **RFC 8032 Ed25519 Cryptographic Engine**: Asymmetric signing with OpenSSL acceleration, dynamic `kid` key rotation, and pure-Python standard-library fallback.
3. **Official Client SDKs (TypeScript & Python)**: Zero-dependency packages (`keyforge-verify`) with native MCP `@metered` tool wrappers and auto-refunds.
4. **Atomic Token-Bucket Quotas**: SQLite WAL persistence with guaranteed zero-overdraft concurrent debiting.
5. **Stripe & LemonSqueezy Integrations**: Signed webhook handlers for automated signups, renewals, payment failures, and tier upgrades.
6. **Editorial Engineering Console**: Warm paper & charcoal interactive dashboard at `/` for live testing, offline verification, and credit simulation.
7. **Production Docker Container**: Pull directly from GitHub Container Registry (`ghcr.io/arceedev/keyforge:1.1.0`) or deploy with Docker Compose.
8. **152 Deterministic Tests**: 7-gate automated production verification suite ensuring cryptographic compliance, schema integrity, and ACID debit guarantees.

### Pricing Options:
- **Indie Developer License ($149)**: Use KeyForge for unlimited personal products and commercial projects you own. Free updates to v1.x.
- **Agency / Studio License ($349)**: Use KeyForge for client projects, multi-tenant setups, and commercial distributions. Priority support included.

### Why Buy This Instead of Building It Yourself?
Building proper RFC 8032 signature verification, hardware seat limits, replay-resistant webhook handlers, and race-condition-free SQLite transactions takes at least 40-60 hours of senior engineering time. KeyForge is fully built, tested, and ready to deploy in under 5 minutes.
```

---

## 4. Hacker News "Show HN" Post

**Title**: 
`Show HN: KeyForge – Self-hosted Ed25519 licensing and MCP credit metering`

**URL**: `https://github.com/ArceeDev/keyforge`

**Text**:
```markdown
Hi HN,

I built KeyForge because every licensing service I evaluated for developer tools and MCP servers either cost $50-$200/month (Keygen, Cryptolens) or required an online network ping on every single tool execution.

KeyForge is an open-architecture, self-hosted gateway designed for high-margin software:

1. Asymmetric Licensing (Ed25519): The server signs license tokens (LIC-<TIER>-<PAYLOAD>.<SIG>). Client tools verify the token completely offline using public-key cryptography. To ensure zero client friction, the offline validator uses the native Web Crypto API in JS/TS and standard-library math in Python—no C extensions or binary dependencies required.

2. Strict RFC 8032 Compliance: Enforces Section 5.1.3 rules (canonical y < p, s < L, rejection of x=0 with sign bit 1, and on-curve point validation) to prevent signature malleability.

3. Atomic Quota Metering: For tools that consume cloud AI credits, KeyForge maintains credit ledgers in SQLite WAL mode using `BEGIN IMMEDIATE` transactions. In our concurrent benchmarks (30 simultaneous workers fighting for the last credits), zero overdrafts occurred.

4. Model Context Protocol (MCP) Integration: Provides `@metered` decorators for FastMCP and `@modelcontextprotocol/sdk`. It charges credits before running the tool and automatically sends a signed refund within a 900s window if the underlying LLM call crashes.

5. Tech Stack: FastAPI, SQLite WAL, official Docker container on GHCR, and an editorial engineering console (no heavy frontend framework).

Code and documentation: https://github.com/ArceeDev/keyforge
Docker image: ghcr.io/arceedev/keyforge:1.1.0

Feedback and questions on the crypto implementation or architecture are very welcome.
```

---

## 5. Twitter / X Launch Thread

**Tweet 1 (The Hook)**:
> If you build paid developer tools, MCP servers, or AI agents, paying $50–$200/mo to licensing SaaS is burning cash.
> 
> Today I'm releasing KeyForge: a self-hosted, air-gapped licensing and credit-metering gateway you can run on a $5 VPS or Docker container.
> 
> Here is how it works (and why pure Ed25519 matters) 🧵👇

**Tweet 2 (The Offline Problem)**:
> Traditional license APIs force your tool to make an HTTP request every time it runs.
> 
> If the user is offline, on a flight, or the auth server is slow, your tool hangs.
> 
> KeyForge uses asymmetric Ed25519 signing. The client verifies the token locally in < 1ms with ZERO network calls.

**Tweet 3 (Zero Dependencies)**:
> Client SDKs (`keyforge-verify` on npm and PyPI) have 0 heavy dependencies.
> 
> - In TS: Uses native Web Crypto API (Node ≥18.4, Bun, Deno, browsers).
> - In Python: Uses pure standard library with OpenSSL acceleration if present.
> 
> No C compilers, no broken native wheels on Windows/Linux/macOS.

**Tweet 4 (Atomic Concurrency & MCP Refunds)**:
> For metered API credits, KeyForge uses SQLite WAL with `BEGIN IMMEDIATE` transactions.
> 
> Tested under 30 concurrent threads: 0 race conditions, 0 overdrafts.
> 
> Plus, native MCP wrappers: if an external Claude/OpenAI call fails mid-flight, KeyForge automatically issues an atomic refund within a 900-second window.

**Tweet 5 (Docker & GitHub Release)**:
> KeyForge v1.1.0 is production-ready with 167 deterministic tests and 7 architectural gates.
> 
> 📦 Docker: `docker pull ghcr.io/arceedev/keyforge:1.1.0`
> 💻 GitHub: https://github.com/ArceeDev/keyforge
> 🌐 Website: https://arceedev.github.io/keyforge/
> 
> Retweet if you believe developers should own their licensing infrastructure!

---

## 6. Configuración Oficial de Stripe Registrada

| Nivel / Producto | Product ID | Price ID | Precio / Tipo | Enlace de Pago (Payment Link) | Metadata |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **KeyForge Indie License** | `prod_VY17LetY3Zgxmd` | `price_1UWv5I02SPcNSlQyW3ueUndQ` | $149 USD (Pago único) | [Comprar Indie ($149)](https://buy.stripe.com/test_cNi14fbm0gsecQo0HLbAs00) | `tier: indie` |
| **KeyForge Agency License** | `prod_VY17xoRTfQMXh1` | `price_1UWv5J02SPcNSlQyqEt0Um9r` | $349 USD (Pago único) | [Comprar Agency ($349)](https://buy.stripe.com/test_5kQcMXdu81xk7w4bmpbAs01) | `tier: agency` |
| **KeyForge Pro (Monthly)** | `prod_...` | `price_...` | $29 USD / mes (Recurrente) | [Suscribir Pro ($29/mo)](https://buy.stripe.com/test_dRmfZ9eyc1xk6s01LPbAs02) | `tier: pro` |
| **KeyForge Studio (Monthly)** | `prod_...` | `price_...` | $89 USD / mes (Recurrente) | [Suscribir Studio ($89/mo)](https://buy.stripe.com/test_cNi3cneyc7VI2bKduxbAs03) | `tier: studio` |

> **Nota sobre Impuestos e IVA (Managed Payments)**:
> Tu cuenta de Stripe tiene **Managed Payments activo**. Stripe actúa como Merchant of Record (MoR) gestionando el IVA y los impuestos mundiales automáticamente.
> - Código fiscal Indie / Agency: `Downloadable Software - Business Use`
> - Código fiscal Pro / Studio: `SaaS - Business Use`

### Webhook Oficial Configurado:
- **Webhook ID**: `we_1UWv5N02SPcNSlQySnK86Nxu`
- **Endpoint URL**: `https://licenses.arceedev.com/api/v1/webhooks/stripe`
- **Estado**: Activo
- **Eventos escuchados**:
  1. `checkout.session.completed` (Emite la licencia de forma automática con los créditos y asientos correspondientes).
  2. `invoice.payment_succeeded` (Renueva ciclos de suscripción o recargas de cuotas).
  3. `customer.subscription.deleted` (Gestiona cancelaciones y revocaciones).
- **Firma del Webhook (`whsec_...`)**:
  Visible en el Dashboard de Stripe (*Developers -> Webhooks -> Signing secret*). Configúralo en la variable `STRIPE_WEBHOOK_SECRET` de la gateway cuando quieras procesar eventos reales.
