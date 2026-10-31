# keyforge-verify

Offline verifier for KeyForge license tokens (`LIC-<TIER>-<PAYLOAD>.<SIGNATURE>`). It is pure Python standard library: no C compiler and no dependencies. If `cryptography` is installed it is used automatically (`pip install keyforge-verify[fast]`).

```python
from keyforge_verify import verify_license
r = verify_license("LIC-PRO-eyJ...", PUBLIC_KEY_HEX, machine_id="ws-node-01")
if not r: raise SystemExit(r.error)  # e.g. ERR_LICENSE_EXPIRED
print(r.payload["tier"], r.payload["features"])
```

## MCP servers

```python
from keyforge_verify.mcp import KeyForge
kf = KeyForge()  # KEYFORGE_LICENSE, KEYFORGE_PUBLIC_KEYS, KEYFORGE_URL, KEYFORGE_CHECKOUT_URL

@mcp.tool()
@kf.require_license(features=["core"])  # offline only
def search(query: str) -> str: ...

@mcp.tool()
@kf.metered(credits=5)                  # offline check + POST /api/v1/quota/deduct
async def summarize(url: str) -> str: ...
```

- Works with sync and async tools and with MCPServer / FastMCP (`mcp` v1 and v2). Put the KeyForge decorator **below** `@mcp.tool()`. The signature is preserved, so the tool schema does not change.
- `@metered` charges **before** the tool runs. It sends an automatic `Idempotency-Key` and reuses it on its single network retry, so a retry never charges twice.
- Failures raise `LicenseError`, a subclass of the SDK's standard MCP error. The client receives a JSON-RPC error: `-32040` invalid license, `-32041` feature not in plan, `-32042` credits exhausted (HTTP 402, with `checkout_url` in `data`), `-32043` gateway error.
- For node-locked licenses the machine id is computed automatically with the same algorithm as the gateway (`keyforge_verify.fingerprint`).

## Key rotation

`public_keys` can be a single hex key, a list of historical keys, or a `{kid: hex}` mapping. Tokens without `kid` (every token issued by KeyForge v1.0) are tried against all the keys. Tokens with a signed `kid` try the matching key first. `r.key_id` tells you which key verified the token.

## Guarantees

- `validate_offline` is a byte-for-byte copy of the gateway's `offline_validator.py`. A test fails if the two drift apart.
- The same 43 conformance vectors as the npm `keyforge-verify` package, run on both the OpenSSL path and the pure RFC 8032 path.

```bash
python -m unittest discover -s tests   # from sdks/python-verify, with src on PYTHONPATH or after pip install -e .
```
