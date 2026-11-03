# keyflint-verify

Offline verifier for KeyFlint license tokens (`LIC-<TIER>-<PAYLOAD>.<SIGNATURE>`), with no runtime dependencies. It uses the native Web Crypto Ed25519 API and works on Node.js ≥ 18.4, Bun, Deno and modern browsers.

```ts
import { verifyLicense } from "keyflint-verify";
const r = await verifyLicense("LIC-PRO-eyJ...", PUBLIC_KEY_HEX, { machineId: "ws-node-01" });
if (!r.valid) throw new Error(r.error); // e.g. ERR_LICENSE_EXPIRED
console.log(r.payload.tier, r.payload.features);
```

`machineId` is required only for node-locked licenses. Pass `domain` when the license has `allowed_domains`.

## MCP servers (`@modelcontextprotocol/sdk`)

```ts
import { createKeyFlint } from "keyflint-verify/mcp";
const kf = createKeyFlint(); // KEYFLINT_LICENSE, KEYFLINT_PUBLIC_KEYS, KEYFLINT_URL, KEYFLINT_CHECKOUT_URL

server.registerTool("search", { inputSchema: { q: z.string() } },
  kf.requireLicense(async ({ q }) => ({ content: [{ type: "text", text: q }] }), { features: ["core"] }));
server.registerTool("summarize", { inputSchema: { url: z.string() } },
  kf.metered(5, async ({ url }) => ({ content: [{ type: "text", text: url }] })));
```

- `requireLicense` is 100% offline. `metered` also calls `POST /api/v1/quota/deduct` **before** running the handler, with an automatic `Idempotency-Key` that it reuses on its single network retry.
- Failures throw `KeyFlintMcpError` (`code`, `message`, `data`, the same shape as the SDK's `McpError`). Codes: `-32060` invalid license, `-32061` feature not in plan, `-32062` credits exhausted (HTTP 402, with `data.checkoutUrl`), `-32063` gateway error (`-32042` is reserved by MCP for URL elicitation). `McpServer` returns the error to the model as an `isError` tool result containing only `message`, so every message states the cause, whether credits were charged, and the next step (with `checkoutUrl` when set).
- The wrappers keep the handler's arguments and types, so they work with `registerTool`, `tool()` or low-level handlers. No runtime dependency on the SDK.

## Activate a license for end users (v1.2)

Your customers do not need to edit `claude_desktop_config.json` by hand:

```bash
npx keyflint-verify activate LIC-PRO-... [--client claude|cursor|windsurf] [--server NAME] [--dry-run]
```

It finds the config of Claude Desktop, Cursor and/or Windsurf for the OS, keeps a `.bak` copy,
sets `env.KEYFLINT_LICENSE` on the server that already uses KeyFlint (or the only server, or
`--server NAME`), and checks the result is valid JSON. Invalid JSON is never modified.
`uvx keyflint-verify activate` (PyPI) does the same.

## Key rotation

`publicKeys` accepts three forms:

```ts
verifyLicense(t, "0043b5...");                          // a single key
verifyLicense(t, [newKey, oldKey]);                     // historical keys
verifyLicense(t, { k2026: newKey, legacy: oldKey });    // keys indexed by kid
```

Tokens without `kid` (every token issued by KeyFlint v1.0) are checked against all the keys. With a `{ kid: hex }` map, a token with a signed `kid` is checked only against that key (`ERR_UNKNOWN_KID` if absent); strings and arrays have no names, so every key is tried. `KEYFLINT_PUBLIC_KEYS` accepts the gateway's published keyring (`k2=hex,legacy-1=hex`) and mixed lists (`oldhex,k2=newhex`). To contain a leaked key, remove it from the ring: a retired key keeps verifying the tokens it signed. `result.keyId` tells you which key verified the token.

When verifying many tokens, use `createVerifier(keys, defaults)`, which imports each key only once.

## Guarantees

- Error codes and acceptance rules match `offline_validator.py`. This is checked against `sdks/vectors/vectors.json` (50 vectors generated from the backend).
- RFC 8032 §5.1.3 strictness before calling Web Crypto: rejects `s ≥ L`, non-canonical `y ≥ p` and `x = 0` with sign bit 1.
- `verifyLicense` never throws on invalid input. `ERR_CRYPTO_UNAVAILABLE` means the runtime lacks Web Crypto Ed25519 (Chrome < 137, Safari < 17, Firefox < 129).
- `decodeLicense(token)` reads the token **without verifying it**. Use it for display only.

## Development

```bash
npm install && npm test       # tsc build (ESM + CJS) + node:test against the vectors
python sdks/vectors/generate_vectors.py   # regenerate vectors from the backend (project root)
```
