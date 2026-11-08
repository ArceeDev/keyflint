// Local Ed25519 issuer for development: signs licenses that keyflint-verify accepts offline,
// so a freshly scaffolded server runs before any gateway exists. Never ship the private key.
import { createPrivateKey, createPublicKey, generateKeyPairSync, sign } from "node:crypto";

const b64url = (buf) => Buffer.from(buf).toString("base64url");

/** Same bytes as Python json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True). */
export function canonicalJson(value) {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "string") {
    return JSON.stringify(value).replace(/[\u0080-￿]/g, (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"));
  }
  if (typeof value === "number") {
    // Python and JS print some floats differently; licenses only carry integers.
    if (!Number.isSafeInteger(value)) throw new TypeError(`canonicalJson: only safe integers are supported, got ${value}`);
    return String(value);
  }
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  if (typeof value === "object") {
    const keys = Object.keys(value).filter((k) => value[k] !== undefined).sort();
    return "{" + keys.map((k) => canonicalJson(k) + ":" + canonicalJson(value[k])).join(",") + "}";
  }
  throw new TypeError(`canonicalJson: unsupported type ${typeof value}`);
}

/** New issuer key. `privatePem` stays local; `publicHex` is what servers trust. */
export function generateIssuer() {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  return {
    privatePem: privateKey.export({ type: "pkcs8", format: "pem" }).toString(),
    publicHex: Buffer.from(publicKey.export({ format: "jwk" }).x, "base64url").toString("hex"),
  };
}

export function publicHexFromPem(privatePem) {
  const jwk = createPublicKey(createPrivateKey(privatePem)).export({ format: "jwk" });
  return Buffer.from(jwk.x, "base64url").toString("hex");
}

/** LIC-<TIER>-<b64url(canonical payload)>.<b64url(signature)> — the gateway's token format. */
export function signLicense(privatePem, payload) {
  if (typeof payload.tier !== "string" || !/^[a-z0-9_]+$/i.test(payload.tier)) {
    throw new TypeError("signLicense: payload.tier must be a non-empty [A-Za-z0-9_] string");
  }
  const bytes = Buffer.from(canonicalJson(payload), "utf8");
  const sig = sign(null, bytes, createPrivateKey(privatePem));
  return `LIC-${payload.tier.toUpperCase()}-${b64url(bytes)}.${b64url(sig)}`;
}

/** Development license: no expiry by default, all features, marked as local. */
export function devLicense(privatePem, { kid = "dev", subject = "dev@localhost", features = ["core"], days = 0, now = Date.now() } = {}) {
  const issued = Math.floor(now / 1000);
  return signLicense(privatePem, {
    kid,
    tier: "dev",
    license_id: "dev-" + issued.toString(36),
    sub: subject,
    features,
    issued_at: issued,
    ...(days > 0 ? { expires_at: issued + days * 86400 } : {}),
  });
}
