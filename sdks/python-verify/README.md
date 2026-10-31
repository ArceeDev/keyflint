# keyforge-verify

Offline verifier for KeyForge license tokens (`LIC-<TIER>-<PAYLOAD>.<SIGNATURE>`). It is pure Python standard library: no C compiler and no dependencies. If `cryptography` is installed it is used automatically (`pip install keyforge-verify[fast]`).

```python
from keyforge_verify import verify_license
r = verify_license("LIC-PRO-eyJ...", PUBLIC_KEY_HEX, machine_id="ws-node-01")
if not r: raise SystemExit(r.error)  # e.g. ERR_LICENSE_EXPIRED
print(r.payload["tier"], r.payload["features"])
```

## Key rotation

`public_keys` can be a single hex key, a list of historical keys, or a `{kid: hex}` mapping. Tokens without `kid` (every token issued by KeyForge v1.0) are tried against all the keys. Tokens with a signed `kid` try the matching key first. `r.key_id` tells you which key verified the token.

## Guarantees

- `validate_offline` is a byte-for-byte copy of the gateway's `offline_validator.py`. A test fails if the two drift apart.
- The same 43 conformance vectors as the npm `keyforge-verify` package, run on both the OpenSSL path and the pure RFC 8032 path.

```bash
python -m unittest discover -s tests   # from sdks/python-verify, with src on PYTHONPATH or after pip install -e .
```
