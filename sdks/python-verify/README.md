# keyflint-verify

Offline verifier for KeyFlint license tokens (`LIC-<TIER>-<PAYLOAD>.<SIGNATURE>`). It is pure Python standard library: no C compiler and no dependencies. If `cryptography` is installed it is used automatically (`pip install keyflint-verify[fast]`).

```python
from keyflint_verify import verify_license
r = verify_license("LIC-PRO-eyJ...", PUBLIC_KEY_HEX, machine_id="ws-node-01")
if not r: raise SystemExit(r.error)  # e.g. ERR_LICENSE_EXPIRED
print(r.payload["tier"], r.payload["features"])
```

## MCP servers

```python
from keyflint_verify.mcp import KeyFlint
kf = KeyFlint()  # KEYFLINT_LICENSE, KEYFLINT_PUBLIC_KEYS, KEYFLINT_URL, KEYFLINT_CHECKOUT_URL

@mcp.tool()
@kf.require_license(features=["core"])  # offline only
def search(query: str) -> str: ...

@mcp.tool()
@kf.metered(credits=5)                  # offline check + POST /api/v1/quota/deduct
async def summarize(url: str) -> str: ...
```

- Works with sync and async tools and with MCPServer / FastMCP (`mcp` v1 and v2). Put the KeyFlint decorator **below** `@mcp.tool()`. The signature is preserved, so the tool schema does not change.
- `@metered` charges **before** the tool runs. It sends an automatic `Idempotency-Key` and reuses it on its single network retry, so a retry never charges twice.
- Failures raise `LicenseError`, a subclass of the SDK's standard MCP error. The client receives a JSON-RPC error: `-32060` invalid license, `-32061` feature not in plan, `-32062` credits exhausted (HTTP 402, with `checkout_url` in `data`), `-32063` gateway error (`-32042` is reserved by MCP for URL elicitation). Each message states the cause, whether credits were charged, and the next step.
- For node-locked licenses the machine id is computed automatically with the same algorithm as the gateway (`keyflint_verify.fingerprint`).

## Activate a license for end users (v1.2)

Your customers do not need to edit `claude_desktop_config.json` by hand:

```bash
uvx keyflint-verify activate LIC-PRO-... [--client claude|cursor|windsurf] [--server NAME] [--dry-run]
```

It finds the config of Claude Desktop, Cursor and/or Windsurf for the OS, keeps a `.bak` copy,
sets `env.KEYFLINT_LICENSE` on the server that already uses KeyFlint (or the only server, or
`--server NAME`), and checks the result is valid JSON. Invalid JSON is never modified.
`npx keyflint-verify activate` does the same.

## Key rotation

`public_keys` can be a single hex key, a list of historical keys, or a `{kid: hex}` mapping. Tokens without `kid` (every token issued by KeyFlint v1.0) are tried against all the keys. With a `{kid: hex}` mapping, a token with a signed `kid` is checked only against that key (`ERR_UNKNOWN_KID` if absent); strings and lists are tried key by key. `KEYFLINT_PUBLIC_KEYS` accepts the gateway's published keyring and mixed lists (`oldhex,k2=newhex`). To contain a leaked key, remove it from the ring. `r.key_id` tells you which key verified the token.

## Guarantees

- `validate_offline` is a byte-for-byte copy of the gateway's `offline_validator.py`. A test fails if the two drift apart.
- Tokens whose signed `issued_at` is more than 300 s ahead of the local clock fail with `ERR_CLOCK_BEFORE_ISSUANCE` (rolled-back clock). Expiry has no extra tolerance. Offline checks cannot stop a determined clock rollback; use short expirations with online renewal when that matters.
- The same 50 conformance vectors as the npm `keyflint-verify` package, run on both the OpenSSL path and the pure RFC 8032 path.

```bash
python -m unittest discover -s tests   # from sdks/python-verify, with src on PYTHONPATH or after pip install -e .
```
