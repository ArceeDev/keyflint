# Web Intel MCP (metered by KeyFlint)

Agent-ready web intelligence, billed per call in KeyFlint credits. Failed fetches are refunded
automatically; invalid input is rejected before any debit.

| Tool | Credits | Returns |
|---|---|---|
| `read_url` | 1 | Main content as clean Markdown (nav, footer, cookie banners removed) |
| `page_metadata` | 1 | Title, description, canonical, lang, robots, Open Graph, JSON-LD types, H1-H3, image alt stats |
| `extract_links` | 1 | Deduplicated internal / external links with anchor text |
| `tech_stack` | 2 | Frameworks, CMS, analytics, payments, CDN/hosting, security headers |
| `seo_audit` | 3 | 0-100 score, A-F grade, 16 weighted checks, top 5 fixes |
| `compare_seo` | 3 x URLs | Ranks 2-5 pages (you vs competitors); only fetched URLs are billed |
| `pricing`, `credits_balance` | free | Price list, remaining credits |

Prices are overridable: `WEB_INTEL_PRICES="seo_audit=5,read_url=2"`.

## Two ways to sell it

**1. Hosted (recommended: paid logic stays on your server).** One process bills many buyers; each
request carries the buyer's license.

```bash
docker build -t web-intel mcps/web-intel
docker run -p 8080:8080 \
  -e KEYFLINT_PUBLIC_KEYS=<issuer-public-hex> \
  -e KEYFLINT_URL=https://licenses.keyflint.dev \
  -e KEYFLINT_CHECKOUT_URL=https://keyflint.dev/buy \
  web-intel
```

Buyers connect to `https://<host>/mcp` (Streamable HTTP, stateless) with
`Authorization: Bearer LIC-...` (or `X-KeyFlint-License`). Missing or forged licenses get `-32060`.

**2. Local stdio (Claude Desktop, Cursor...).** The license comes from the environment.

```json
{
  "mcpServers": {
    "web-intel": {
      "command": "uvx",
      "args": ["keyflint-web-intel"],
      "env": {
        "KEYFLINT_LICENSE": "LIC-...",
        "KEYFLINT_PUBLIC_KEYS": "<issuer-public-hex>",
        "KEYFLINT_URL": "https://licenses.keyflint.dev"
      }
    }
  }
}
```

## Billing flow per call

1. URL validated (http/https only). Bad input: error, nothing charged.
2. Offline Ed25519 license check (`keyflint-verify`), cached 60 s.
3. `POST /api/v1/quota/deduct` with a fresh idempotency key. Out of credits: `-32062` with the checkout link.
4. Fetch + analysis. If anything fails: `POST /api/v1/quota/refund` (same key), the client gets `isError`.

## Safety

Requests to private, loopback and link-local addresses are refused (checked on every redirect hop),
responses are capped at 3 MB (`WEB_INTEL_MAX_BYTES`), 15 s timeout (`WEB_INTEL_TIMEOUT`), max 5 redirects.
`WEB_INTEL_ALLOW_PRIVATE=1` disables the address check (tests only).

## Tests

End-to-end against a real KeyFlint gateway (spawned from this repo) and a local test site:

```bash
pip install -e sdks/python-verify -e "mcps/web-intel[test]" -r requirements.txt
python -m pytest mcps/web-intel/tests -q
```
