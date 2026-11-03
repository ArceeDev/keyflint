# KeyFlint v1.2.2 · Plan y posts de lanzamiento

Revisado 2026-11-03. Día D: **martes 10-nov-2026, 16:30 Madrid** (8:30 PT).
Enlaces: `https://keyflint.dev` · `https://github.com/ArceeDev/keyflint` · `support@keyflint.dev`.

## ⛔ Pendiente antes del día D

| # | Qué | Quién | Estado |
|---|---|---|---|
| 1 | **Revisión legal de privacy/DPA.** PR #41 las pasa a inglés con aviso "Draft pending legal review" y checklist `internal/legal/LAWYER_REVIEW.md`. La landing ya vende **Pro Cloud $29/mo (Managed)**: o revisión legal antes de D, o quitar/ocultar Pro y Studio en el copy y en la landing hasta entonces. | Arcee + abogado | Abierto |
| 2 | Fusionar PR #40 (versión 1.2.2), #41 (legal EN), #42 (`@keyflint/wrap` + `.mcpb`). | Arcee / Antigravity | ✓ Hecho (PRs #40, #41, #42 fusionadas) |
| 3 | `@keyflint/wrap`: crear la org npm `keyflint` y `npm publish` en `sdks/js-wrap` (OTP). Si no se publica antes de D, **borra las líneas marcadas [WRAP]** de los posts. | Arcee | Abierto |
| 4 | Botón "Deploy on Railway": quitado de landing y README para evitar despliegues sin volumen persistente. | Antigravity | ✓ Hecho |
| 5 | Clave Ed25519 en `.txt` plano → gestor/USB cifrado. | Arcee | Abierto |
| 6 | Search Console + sitemap enviado. | Arcee | ✓ Hecho |
| 7 | Deploy de la imagen 1.2.2 en Fly. | Antigravity | ✓ Hecho |
| 8 | Landing en inglés, Founder $199 (100 uds., Payment Link con límite), SEO/guía, monitor. | — | ✓ Hecho (PR #32-#38) |
| 9 | `[BENCH]` 0.116 ms con `cryptography`, 3.0 ms Python puro. `[PRICE]` LS 5%+50¢, Gumroad 10%+50¢; Keygen sin cifra verificable (no citar $49). | — | ✓ Hecho |

## 1. Calendario

| Cuándo | Qué |
|---|---|
| D-7 → D-3 | Cerrar la tabla de arriba. Listar en directorios MCP (Glama, mcp.so, PulseMCP, Smithery) y PR a `awesome-mcp-servers`. 2-3 servidores de ejemplo con `@metered` (`examples/monetized-mcp-server`) y uno con `@keyflint/wrap` [WRAP]. |
| D-2 | Ensayo: compra Founder real → correo → verificación offline → reembolso (comprueba que el contador del Payment Link vuelve a 99 o anótalo). GIF de 20 s para X. |
| **D 16:30** | **Show HN** + primer comentario en <2 min. Responder 4 h, cada 15-20 min. |
| D 18:00 | Hilo de X (enlaza al HN). |
| D+1 | r/mcp + Discord MCP. |
| D+2 | r/selfhosted (mira la regla de proyectos nuevos del sidebar). |
| D+3 / sábado | r/MachineLearning `[P]`, sin precios. |
| D+7 | DMs a 10-15 creadores de MCP (§6). Un seguimiento máx. a D+14. |

Regla: un canal por día. Nunca pidas votos. No edites el título de HN tras publicar.

---

## 2. Show HN

**Título:**
```
Show HN: KeyFlint – Offline Ed25519 licenses and metered credits for MCP tools
```
**URL:** `https://github.com/ArceeDev/keyflint`

**Primer comentario:**
```
Hi HN,

I build small developer tools and kept hitting the same wall: there's no simple
way to charge for an MCP server or a CLI without renting a licensing SaaS
monthly or giving a marketplace a cut of every sale. So I built the piece I
wanted.

KeyFlint is a license and usage-credit gateway you can self-host (one
container) or use as a managed instance. Design choices:

- Licenses are Ed25519-signed tokens verified offline: the client never calls
  home to check a key. Tokens carry a `kid`, so you can rotate signing keys and
  retired public keys keep validating old licenses.
- ~0.12 ms per verification with `cryptography` (~3 ms pure Python), cheap
  enough to run on every tool call.
- Credits live in SQLite (WAL), single writer by design. Deductions are atomic
  and idempotent. Litestream streams backups to object storage and a restore is
  tested every hour.
- For MCP servers, `@metered(credits=5)` (Python/TS) deducts before the tool
  runs and refunds if it throws or returns isError. A deduct that arrives after
  its refund is rejected, and a refund circuit breaker (count- and
  credit-weighted) stops "fail on purpose" abuse.
- [WRAP] Don't want to touch your server's code? `npx @keyflint/wrap --tool
  search=5 -- python server.py` gates any stdio MCP server, and there's a
  .mcpb template so buyers install it in Claude Desktop with their key stored
  as a sensitive setting.
- Errors are JSON-RPC -32060..-32063, outside the codes MCP already uses.
- Verifier SDKs for Python, TypeScript and Go (MIT), all checked against the
  same 50 conformance vectors.

  pip install keyflint-verify
  npm i keyflint-verify
  go get github.com/ArceeDev/keyflint/sdks/go-verify@v1.2.0

Licensing: gateway BSL 1.1 (Apache 2.0 on 2030-10-31), SDKs MIT.
Pricing: free Community tier; self-hosted Indie $149 one-time; managed from
$29/mo. For launch, a Founder license at $199 one-time for the first 100
buyers (Indie + every v1.x and v2.x update).

Known limits: single node by design, no Rust SDK yet.

I'd especially like feedback on the refund/replay semantics and whether offline
verification + key rotation covers the threat model you care about for paid
CLIs.
```
Si Managed no está listo (bloqueo 1): sustituye "or use as a managed instance" por nada y "managed from $29/mo" por "a managed tier is coming".

Respuestas preparadas: ¿por qué no Keygen? (offline, sin comisión, autoalojable; sin atacar) · ¿open source? (source-available BSL, SDKs MIT) · ¿multi-nodo? (no: SQLite un escritor, a propósito) · ¿Rust? (no aún; los 50 vectores sirven para escribirlo).

---

## 3. r/mcp y Discord MCP

**Título r/mcp:**
```
I built per-call billing for MCP servers: one decorator (or zero code), auto-refund on errors
```
**Texto:**
```
If you want to charge for an MCP server, KeyFlint gives you:

@metered(credits=5)
async def search_docs(query): ...

- Each call deducts credits atomically; if the tool throws or returns isError,
  the credits come back (users don't pay for your bugs).
- [WRAP] No code changes option: `npx @keyflint/wrap --tool search_docs=5 --
  python server.py` wraps any stdio server. A .mcpb template turns it into a
  one-file Claude Desktop extension; the buyer pastes the key once.
- Licenses are Ed25519, verified offline. Clear JSON-RPC errors
  (-32060..-32063) when a key is invalid or out of credits.
- SDKs: pip/npm `keyflint-verify`, Go module. MIT.

Self-host it or use the managed gateway. Free Community tier to try it.
Repo: https://github.com/ArceeDev/keyflint

Happy to help wire it into your server, drop your repo below.
```
**Discord (corto):**
```
Shipped KeyFlint v1.2: per-call billing for MCP tools with `@metered(credits=N)` [WRAP: or zero-code with `npx @keyflint/wrap -- <your server>`], auto-refund when a tool errors, offline Ed25519 licenses. Python/TS/Go SDKs (MIT). Free tier. https://github.com/ArceeDev/keyflint – feedback on the error codes (-32060..-32063) welcome.
```

---

## 4. r/selfhosted

**Título:**
```
KeyFlint: self-hosted license server + usage credits for your own tools (FastAPI + SQLite, one container)
```
**Texto:**
```
I sell a couple of small dev tools and didn't want a monthly licensing SaaS or a
marketplace cut, so I built a license server I can run myself.

- One container: FastAPI + SQLite (WAL). No Redis/Postgres.
- Optional Litestream replication to S3/R2 with an hourly restore test and a
  healthcheck ping.
- Ed25519 licenses verified offline by your app (Python/TS/Go SDKs, MIT).
- Usage credits with atomic deduct/refund.
- Stripe webhooks, web console, CLI (`init` generates keys and config).
- Deploy on Fly / Render, or plain `docker run`. Image pinned with hashes,
  SBOM and dependency audit in CI.

License: BSL 1.1 for the gateway (Apache 2.0 in 2030): self-hosting for your
own products is allowed; reselling it as a competing hosted service isn't.
Free Community tier and a one-time paid license; managed is optional.

Repo + Quickstart: https://github.com/ArceeDev/keyflint
```

---

## 5. r/MachineLearning

**Título:**
```
[P] Metered billing for LLM tool calls via MCP: atomic credits with automatic refunds on tool failure
```
**Texto:**
```
Agents call tools in loops, retry on failure and fan out in parallel, which
makes naive per-call billing unfair (users pay for failed calls) and unsafe
(retries can be replayed, refunds can be farmed). I built KeyFlint to handle
this for MCP tool servers.

- Credits are reserved before the tool runs and refunded if it raises or
  returns isError, within a 900 s window. Deduct and refund are idempotent by
  request id; a deduct arriving after its refund is rejected.
- A refund circuit breaker looks at both the share of refunded calls and the
  share of refunded credits, so padding with cheap successful calls doesn't
  hide expensive failures.
- Entitlements are Ed25519-signed tokens verified offline, with `kid`-based key
  rotation, so the hot path needs no network call.
- SQLite WAL; Python/TS/Go verifiers share 50 conformance vectors.

Interested in how others handle cost attribution for agent tool calls,
especially partial failures and streaming tools.

Code (gateway BSL 1.1, SDKs MIT): https://github.com/ArceeDev/keyflint
```
Sin precios ni "compra". Si lo eliminan, no lo repitas.

---

## 6. Hilo de X (6 posts)

**1/**
```
You built an MCP server people actually use.

Now you want to charge for it without a monthly licensing SaaS or a 10% + 50¢ cut on every sale.

Here's how with one decorator 🧵
```
**2/** (adjunta el GIF)
```
@metered(credits=5)
async def search_docs(query): ...

Each call deducts 5 credits, atomically.
Tool throws or returns isError? The credits come back.

Your users never pay for your bugs.
```
**3/** [WRAP]
```
Don't want to touch your server's code?

npx @keyflint/wrap --tool search=5 -- python server.py

Any stdio MCP server, gated and metered. Plus a .mcpb template: one-file Claude Desktop install, key pasted once.
```
**4/**
```
Licenses are Ed25519 tokens verified offline.

No phone-home, ~0.12 ms per check.
Rotate keys via `kid`; old licenses keep working.
```
**5/**
```
pip install keyflint-verify
npm i keyflint-verify
go get github.com/ArceeDev/keyflint/sdks/go-verify

MIT SDKs, 50 shared test vectors. Self-host in one container.
```
**6/**
```
KeyFlint v1.2 is live.

Free Community · Indie $149 one-time · Managed from $29/mo
Founder: $199 once, first 100 buyers only (Indie + every v1.x and v2.x update).

On HN today, feedback welcome 👇
[link HN]
```
Nunca "lifetime updates" para Founder.

---

## 7. DM a creadores de MCP

**Asunto:** Monetizar {{repo}} sin comisiones
```
Hi {{name}},

I've been looking at {{repo}}, and {{specific detail}}. It clearly has real users, so I'll be brief.

I built KeyFlint, which lets you charge per call on an MCP server, either with one decorator, @metered(credits=5), or with no code changes by wrapping the server with npx @keyflint/wrap. Licenses are Ed25519 and verified offline, credits refund automatically if a tool fails, and payments go straight to your own Stripe.

If useful, I'll put together a free example integration on {{repo}} so you can see how it'd look. If it doesn't fit your plans, no need to reply.

{{your name}}
https://keyflint.dev
```
Email público o Discussions, nunca issues. Sin [WRAP] publicado, quita "or with no code changes...".

---

## 8. Precios (referencia; + IVA)

| Tier | Precio | Incluye |
|---|---|---|
| Community | Gratis | 25 créditos, 1 nodo |
| Indie | $149 único | 10k créditos, 3 seats, perpetua |
| Agency | $349 único | 50k créditos, 25 seats, perpetua |
| Pro Cloud (Managed) | $29/mes | Gateway gestionado ⚠ bloqueo 1 |
| Studio | $89/mes | Managed, soporte ≤1 día laborable ⚠ bloqueo 1 |
| Founder (tier `lifetime`) | $199 único | Máx. 100 (límite del Payment Link). = Indie + v1.x y v2.x. Sin Managed. |

Soporte: Indie/Founder/Pro ≤2 días laborables; Agency/Studio ≤1. Reembolso 14 días.

---

## 9. Checklist del día D

**Mañana (antes de las 16:00)**
- [ ] `https://licenses.keyflint.dev/api/v1/health` → `healthy: true`, `backup.status: ok`, versión 1.2.2.
- [ ] healthchecks.io verde; Fly con margen (NUNCA 2 máquinas; si falta, `fly scale memory 512`).
- [ ] Issue `outage` = 0 y último *Production monitor* verde.
- [ ] Landing: precios = §8, enlaces live (Founder incluido), privacy/DPA en inglés enlazadas.
- [ ] Compra con cupón 100% → correo (Gmail + iCloud) → licencia verifica.
- [ ] `pip install`, `npm i`, `go get` (y `npx @keyflint/wrap --help` [WRAP]) en máquina limpia.
- [ ] README Quickstart probado copiando y pegando.
- [ ] support@keyflint.dev abierto con respuestas preparadas (§2).

**Lanzamiento**
- [ ] 16:30 Show HN + primer comentario.
- [ ] 18:00 hilo de X.
- [ ] Responder en HN cada 15-20 min durante 4 h.

**Noche / D+1**
- [ ] Stripe (pagos, disputas, contador Founder), logs de Fly, correos fallidos (`resend-license`).
- [ ] Preguntas repetidas → FAQ del README.
- [ ] Métricas: visitas (Cloudflare), estrellas, npm/PyPI, compras por tier.
