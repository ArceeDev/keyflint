# KeyForge — Commercial Launch & Distribution Kit (Zero-Slop Edition)

> **Objective**: Monetize KeyForge immediately with zero corporate fluff or AI clichés. This document contains battle-tested sales copy, technical positioning, launch templates, and the exact go-to-market playbook.

---

## 1. Grounded Technical Positioning

### The Problem
If you build a paid developer CLI, Model Context Protocol (MCP) server, local AI tool, or desktop app, licensing is a nightmare:
1. **Hosted Licensing SaaS is Expensive**: Services like Keygen.sh or Cryptolens charge **$49 to $499 every single month**, eating your margin before you even validate product-market fit.
2. **Platform Keys are Fragile**: Gumroad/Whop license keys require an HTTP ping on every run. If the user is on an airplane, in a secure corporate network, or the platform API is slow, your tool hangs.
3. **Custom Solutions Have Bugs**: Rolling your own crypto verification usually ends up with signature malleability issues, race conditions during credit debits, or requiring heavy C dependencies that break across client OS platforms.

### The KeyForge Value Proposition
- **Self-Hosted & Zero Royalty**: Runs as a single Docker container or Python process on a $5/mo VPS. No revenue share, no third-party lock-in.
- **Asymmetric Ed25519 (RFC 8032)**: Private key stays on your server. Clients verify offline using a **single standard-library Python file** (`offline_validator.py`) or browser WebCrypto in `< 1 ms`.
- **Atomic Credit Quota (SQLite WAL)**: High-speed credit metering using `BEGIN IMMEDIATE` transactions with zero overdraft under heavy multi-threaded concurrency.
- **Native Stripe & LemonSqueezy Webhooks**: Automatic provisioning, renewals, grace periods, and tier upgrades.

---

## 2. Ready-to-Paste LemonSqueezy / Gumroad Product Listing

### Product Title
**KeyForge — Self-Hosted Ed25519 Licensing & Credit-Metering Gateway**

### Subtitle
*Stop paying $50/month to licensing SaaS. Ship offline-verifiable software licenses and atomic API credit quotas from your own $5 VPS.*

### Body Description

```markdown
Building a paid CLI, AI agent, MCP server, or developer tool?

You shouldn't have to pay $600/year to Keygen or give up 10% of your revenue to a closed marketplace just to verify license keys and meter usage.

**KeyForge** is a production-grade, self-hosted licensing and credit-metering gateway that runs on your own server and verifies in milliseconds without external dependencies.

### What You Get:
1. **Complete Gateway Source Code**: Hardened FastAPI backend (Python 3.11+) with Clean Architecture and strict static typing.
2. **RFC 8032 Ed25519 Cryptographic Engine**: Asymmetric signing with OpenSSL acceleration and pure-Python standard-library fallback.
3. **Air-Gapped Client Validator**: A single, zero-dependency Python file (`offline_validator.py`) and WebCrypto browser snippet you can vendor directly into client apps.
4. **Atomic Token-Bucket Quotas**: SQLite WAL persistence with guaranteed zero-overdraft concurrent debiting.
5. **Stripe & LemonSqueezy Integrations**: Signed webhook handlers for automated signups, renewals, payment failures, and tier upgrades.
6. **Cyber-Minimalist Dark Web Console**: Real-time license issuance, offline verification tester, credit deduction, and webhook simulation at `/`.
7. **Full CLI**: Manage licenses, nodes, and quotas directly from your terminal (`python -m app.cli`).
8. **Docker & Compose**: Deploy to any VPS in 30 seconds (`docker compose up -d`).
9. **Full Test Suite & Audit Suite**: 69 deterministic E2E tests and a 7-gate automated production verification suite.

### Pricing Options:
- **Indie Developer License ($149)**: Use KeyForge for unlimited personal products and commercial projects you own. Free updates to v1.x.
- **Agency / Studio License ($349)**: Use KeyForge for client projects, multi-tenant setups, and commercial distributions. Priority support included.

### Why Buy This Instead of Building It Yourself?
Building proper RFC 8032 signature verification, hardware seat limits, replay-resistant webhook handlers, and race-condition-free SQLite transactions takes at least 40-60 hours of senior engineering time. KeyForge is fully built, tested, and ready to deploy in under 5 minutes.
```

---

## 3. Hacker News "Show HN" Post

**Title**: 
`Show HN: KeyForge – Self-hosted Ed25519 licensing and SQLite credit metering`

**URL**: `https://github.com/your-username/keyforge` (or your live demo link)

**Text**:
```markdown
Hi HN,

I built KeyForge because every licensing service I evaluated for developer tools and MCP servers either cost $50-$200/month (Keygen, Cryptolens) or required an online network ping on every single tool execution.

KeyForge is an open-architecture, self-hosted gateway designed for high-margin software:

1. Asymmetric Licensing (Ed25519): The server signs license tokens (LIC-<TIER>-<PAYLOAD>.<SIG>). Client tools verify the token completely offline using public-key cryptography. To ensure zero client friction, the offline validator is a single file using only Python's standard library—no C extensions or pip dependencies required.

2. Strict RFC 8032 Compliance: Enforces Section 5.1.3 rules (canonical y < p, s < L, rejection of x=0 with sign bit 1, and on-curve point validation) to prevent signature malleability.

3. Atomic Quota Metering: For tools that consume cloud AI credits, KeyForge maintains credit ledgers in SQLite WAL mode using `BEGIN IMMEDIATE` transactions. In our concurrent benchmarks (30 simultaneous workers fighting for the last credits), zero overdrafts occurred.

4. Webhook Ingestion: Handles Stripe (with multi-v1 signature rotation support) and LemonSqueezy webhooks to automatically replenish credits, extend expiration, or revoke licenses on churn.

5. Tech Stack: FastAPI, Pydantic v2, SQLite WAL, and a vanilla CSS/JS dark console (no npm, no node_modules).

Code and documentation: [link]
Feedback and questions on the crypto implementation or architecture are very welcome.
```

---

## 4. Twitter / X Launch Thread

**Tweet 1 (The Hook)**:
> If you build paid developer tools, MCP servers, or AI agents, paying $50/mo to licensing SaaS is burning cash.
> 
> Today I'm releasing KeyForge: a self-hosted, air-gapped licensing and credit-metering gateway you can run on a $5 VPS.
> 
> Here is how it works (and why pure-Python Ed25519 matters) 🧵👇

**Tweet 2 (The Offline Problem)**:
> Traditional license APIs force your tool to make an HTTP request every time it runs.
> 
> If the user is offline or the auth server is down, your software breaks.
> 
> KeyForge uses asymmetric Ed25519 signing. The client verifies the token locally in < 1ms with ZERO network calls.

**Tweet 3 (Zero Dependencies)**:
> The client-side validator (`offline_validator.py`) has 0 external dependencies.
> 
> No pip install cryptography, no C compiler, no wheel compatibility issues on Windows/Linux/macOS. Just pure Python standard library.
> 
> Also includes native browser WebCrypto verification for web apps.

**Tweet 4 (Atomic Concurrency)**:
> For metered API credits, KeyForge uses SQLite WAL with `BEGIN IMMEDIATE` transactions.
> 
> We tested 30 concurrent workers draining a depleted wallet at the exact same millisecond.
> Result: Exactly 20 debits, 10 paywalls (HTTP 402), 0 overdrafts.

**Tweet 5 (Out-of-the-box Billing)**:
> Connects directly to Stripe and LemonSqueezy webhooks:
> - Auto-provisions licenses upon checkout
> - Renews credits on billing cycles
> - Manages seat hardware locking
> - Issues signed re-keys upon tier upgrades

**Tweet 6 (Call to Action)**:
> KeyForge is production-ready with 69 passing E2E tests, full Docker support, and a Cyber-Minimalist admin console.
> 
> Grab the code here: [link]
> Retweet to support self-hosted developer infrastructure!

---

## 5. Direct Outreach Template (For MCP / AI Tool Creators)

**Subject**: Offline licensing for [Tool Name]

**Body**:
```text
Hey [Name],

Saw [Tool Name]—really slick work on the [specific feature/MCP integration].

Are you currently licensing it or planning to monetize Pro seats? 

I recently open-sourced/released KeyForge (https://github.com/your-username/keyforge)—it's a self-hosted gateway that generates Ed25519-signed licenses and meters credits in SQLite. 

The biggest perk for tools like yours is that clients can verify licenses 100% offline without network lag or relying on third-party licensing SaaS fees ($50+/mo).

Happy to share the single-file client validator if you're looking to add seat locking or Stripe checkout without the headache.

Best,
[Your Name]
```

---

## 6. Real Launch Checklist (15 Minutes to First Dollar)

1. **Deploy Container**:
   ```bash
   git clone <your-repo> keyforge && cd keyforge
   cp .env.production.example .env
   # Edit .env with your generated secrets
   docker compose up -d
   ```
2. **Verify Health**:
   ```bash
   curl -i http://localhost:8000/healthz
   ```
3. **Connect Stripe / LemonSqueezy**:
   - In Stripe: Create a Webhook endpoint pointing to `https://licenses.yourdomain.com/api/v1/webhooks/stripe` listening for `checkout.session.completed`, `invoice.payment_succeeded`, and `customer.subscription.deleted`.
   - Copy the webhook secret into `.env`.
4. **Publish Your Gumroad / LemonSqueezy Store**:
   - Create a Digital Product titled "KeyForge Gateway Source Code".
   - Price at **$149** (Indie) or **$349** (Studio).
   - Paste the copy from Section 2 above.
   - Attach the zipped repository.
5. **Publish Launch Posts**:
   - Post to Hacker News (*Show HN*).
   - Post the Twitter/X thread with a 30-second screen capture of the interactive console at `/`.
   - Submit to Product Hunt and Indie Hackers.
