"""Generate cross-SDK conformance vectors from the KeyForge reference implementation.

Run from the project root:  python sdks/vectors/generate_vectors.py
Expected results come from app.infrastructure.security.offline_validator (both
OpenSSL and pure-Python paths must agree, otherwise generation aborts).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.infrastructure.security.ed25519_signer import Ed25519Signer, b64url_encode  # noqa: E402
from app.infrastructure.security.offline_validator import validate_offline  # noqa: E402

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
NOW = 1_800_000_000

K1 = Ed25519Signer(private_key_hex="11" * 32)  # legacy key (no kid)
K2 = Ed25519Signer(private_key_hex="22" * 32)  # rotated key, kid "k2"
PK1, PK2 = K1.get_public_key_hex(), K2.get_public_key_hex()


def base(**over):
    p = {"license_id": "lic_test", "email": "dev@example.com", "tier": "pro",
         "features": ["core", "cli_offline"], "expires_at": NOW + 3600}
    p.update(over)
    return {k: v for k, v in p.items() if v is not ...}


def tok(signer, payload):
    return signer.sign_token(payload)


def split(t):
    head, sig = t.split(".")
    return head, sig


def enc_point(y, sign=0):
    return (y | (sign << 255)).to_bytes(32, "little")


def py_expected(token, keys, now, machine_id=None, domain=None):
    results = []
    for force in (False, True):
        best = None
        for k in keys:
            r = validate_offline(token, k, now, machine_id, domain, force_pure_python=force)
            if r[0]:
                best = r
                break
            best = best or r
        if not keys:
            best = validate_offline(token, "", now, machine_id, domain, force_pure_python=force)
        results.append((best[0], best[2]))
    if results[0] != results[1]:
        raise SystemExit(f"OpenSSL/pure divergence on {token[:40]}...: {results}")
    return results[0]


V = []


def add(name, token, keys, now=NOW, machine_id=None, domain=None):
    valid, err = py_expected(token, keys, now, machine_id, domain)
    V.append({"name": name, "token": token, "public_keys": keys, "now": now,
              "machine_id": machine_id, "domain": domain,
              "expected": {"valid": valid, "error": err}})


good = tok(K1, base())
add("valid_basic", good, [PK1])
add("valid_perpetual", tok(K1, base(expires_at=None)), [PK1])
add("expired", tok(K1, base(expires_at=NOW - 1)), [PK1])
add("expiry_boundary_equal_is_valid", tok(K1, base(expires_at=NOW)), [PK1])
add("malformed_expiration_bool", tok(K1, base(expires_at=True)), [PK1])
add("malformed_expiration_string", tok(K1, base(expires_at="soon")), [PK1])
add("wrong_key", good, [PK2])
add("empty_token", "", [PK1])
add("no_dot", good.replace(".", ""), [PK1])
add("two_dots", good + ".x", [PK1])
add("bad_prefix", "KEY" + good[3:], [PK1])
add("bad_public_key", good, ["zz" * 32])
add("short_public_key", good, ["00" * 31])
head, sig = split(good)
add("bad_b64_payload", head[:-1] + "!" + "." + sig, [PK1])
add("bad_b64_signature", head + "." + sig[:-1] + "+", [PK1])
add("short_signature", head + "." + sig[:-4], [PK1])
add("payload_tampered", head[:-2] + ("AA" if head[-2:] != "AA" else "BB") + "." + sig, [PK1])
add("tier_header_mismatch", head.replace("LIC-PRO-", "LIC-STUDIO-", 1) + "." + sig, [PK1])
add("tier_header_case_insensitive", head.replace("LIC-PRO-", "LIC-pro-", 1) + "." + sig, [PK1])
# payload that is valid JSON but not an object
raw = b"[1,2,3]"
add("payload_not_object", "LIC-PRO-" + b64url_encode(raw) + "." + b64url_encode(K1.sign_bytes(raw)), [PK1])
raw = b"{not json"
add("payload_not_json", "LIC-PRO-" + b64url_encode(raw) + "." + b64url_encode(K1.sign_bytes(raw)), [PK1])

# node lock
nl = tok(K1, base(machine_id="WS-Node-01"))
add("machine_ok_case_insensitive", nl, [PK1], machine_id=" ws-node-01 ")
add("machine_mismatch", nl, [PK1], machine_id="ws-node-02")
add("machine_missing_expected", nl, [PK1])
add("machine_expected_but_token_unlocked", good, [PK1], machine_id="ws-node-01")
add("machine_id_not_string", tok(K1, base(machine_id=42)), [PK1], machine_id="42")

# domain lock
dl = tok(K1, base(allowed_domains=["api.acme.ai", "*.acme.dev"]))
add("domain_exact", dl, [PK1], domain="API.acme.ai.")
add("domain_exact_with_port", dl, [PK1], domain="api.acme.ai:8443")
add("domain_wildcard_sub", dl, [PK1], domain="x.y.acme.dev")
add("domain_wildcard_apex", dl, [PK1], domain="acme.dev")
add("domain_mismatch", dl, [PK1], domain="evil-acme.dev")
add("domain_missing", dl, [PK1])
add("domain_invalid_chars", dl, [PK1], domain="api.acme.ai/path")
add("domain_underscore_rejected", tok(K1, base(allowed_domains=["a_b.com"])), [PK1], domain="a_b.com")
add("domain_idna", tok(K1, base(allowed_domains=["bücher.example"])), [PK1], domain="xn--bcher-kva.example")
add("domain_empty_list_allows_any", tok(K1, base(allowed_domains=[])), [PK1], domain="anything.com")
add("domain_list_not_strings", tok(K1, base(allowed_domains=[1])), [PK1], domain="a.com")

# clock sanity (issued_at is signed; 300 s of tolerated skew)
iss = tok(K1, base(issued_at=NOW))
add("clock_before_issuance", iss, [PK1], now=NOW - 301)
add("clock_skew_within_leeway", iss, [PK1], now=NOW - 300)
add("issued_at_not_number_ignored", tok(K1, base(issued_at="2027-01-15")), [PK1])

# key ring / rotation
rot = tok(K2, base(kid="k2"))
add("ring_legacy_token_old_key", good, [PK2, PK1])
add("ring_kid_token_new_key", rot, [PK1, PK2])
add("ring_kid_token_without_key", rot, [PK1])
# token claiming kid "k2" but signed by the k1 key (kid binding is checked with named key maps)
add("kid_claim_signed_by_other_key", tok(K1, base(kid="k2")), [PK2])

# RFC 8032 adversarial
sig_b = bytearray(K1.sign_bytes(json.dumps(base(), sort_keys=True, separators=(",", ":")).encode()))
s = int.from_bytes(sig_b[32:], "little")
if s + L < 2**256:
    mall = bytes(sig_b[:32]) + (s + L).to_bytes(32, "little")
    add("malleable_s_plus_L", head + "." + b64url_encode(mall), [PK1])
nc = enc_point(P + 1)  # non-canonical encoding of the identity (y=1)
add("noncanonical_identity_key_and_R", head + "." + b64url_encode(nc + bytes(32)),
    [nc.hex()])
add("x0_sign_bit_R", head + "." + b64url_encode(enc_point(1, 1) + sig_b[32:]), [PK1])

out = Path(__file__).with_name("vectors.json")
out.write_text(json.dumps({"version": 1, "keys": {"k1": PK1, "k2": PK2}, "vectors": V},
                          indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {len(V)} vectors -> {out}")
