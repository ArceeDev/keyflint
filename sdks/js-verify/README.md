# keyforge-verify

Offline verifier for KeyForge license tokens (`LIC-<TIER>-<PAYLOAD>.<SIGNATURE>`), with no runtime dependencies. It uses the native Web Crypto Ed25519 API and works on Node.js ≥ 18.4, Bun, Deno and modern browsers.

```ts
import { verifyLicense } from "keyforge-verify";
const r = await verifyLicense("LIC-PRO-eyJ...", PUBLIC_KEY_HEX, { machineId: "ws-node-01" });
if (!r.valid) throw new Error(r.error); // e.g. ERR_LICENSE_EXPIRED
console.log(r.payload.tier, r.payload.features);
```

`machineId` is required only for node-locked licenses. Pass `domain` when the license has `allowed_domains`.

## Key rotation

`publicKeys` accepts three forms:

```ts
verifyLicense(t, "0043b5...");                          // a single key
verifyLicense(t, [newKey, oldKey]);                     // historical keys
verifyLicense(t, { k2026: newKey, legacy: oldKey });    // keys indexed by kid
```

Tokens without `kid` (every token issued by KeyForge v1.0) are checked against all the keys. Tokens with a signed `kid` in the payload try that key first. `result.keyId` tells you which key verified the token.

When verifying many tokens, use `createVerifier(keys, defaults)`, which imports each key only once.

## Guarantees

- Error codes and acceptance rules match `offline_validator.py`. This is checked against `sdks/vectors/vectors.json` (43 vectors generated from the backend).
- RFC 8032 §5.1.3 strictness before calling Web Crypto: rejects `s ≥ L`, non-canonical `y ≥ p` and `x = 0` with sign bit 1.
- `verifyLicense` never throws on invalid input. `ERR_CRYPTO_UNAVAILABLE` means the runtime lacks Web Crypto Ed25519 (Chrome < 137, Safari < 17, Firefox < 129).
- `decodeLicense(token)` reads the token **without verifying it**. Use it for display only.

## Development

```bash
npm install && npm test       # tsc build (ESM + CJS) + node:test against the vectors
python sdks/vectors/generate_vectors.py   # regenerate vectors from the backend (project root)
```
