/**
 * keyforge-verify — offline verifier for KeyForge license tokens.
 *
 * Token format: LIC-<TIER>-<BASE64URL(canonical JSON payload)>.<BASE64URL(Ed25519 signature)>
 * The signature covers the decoded payload bytes. Behaviour and error codes mirror
 * app/infrastructure/security/offline_validator.py and are pinned by sdks/vectors/vectors.json.
 *
 * Zero runtime dependencies. Uses the Web Crypto API (Node.js >= 18.4, Bun, Deno, modern browsers).
 */

export type ErrorCode =
  | "ERR_EMPTY_TOKEN"
  | "ERR_INVALID_TOKEN_FORMAT"
  | "ERR_INVALID_TOKEN_PREFIX"
  | "ERR_INVALID_PUBLIC_KEY"
  | "ERR_MALFORMED_BASE64_PAYLOAD"
  | "ERR_MALFORMED_BASE64_SIGNATURE"
  | "ERR_INVALID_SIGNATURE_LENGTH"
  | "ERR_SIGNATURE_TAMPERED"
  | "ERR_MALFORMED_JSON_PAYLOAD"
  | "ERR_INVALID_PAYLOAD_STRUCTURE"
  | "ERR_TIER_MISMATCH"
  | "ERR_MALFORMED_EXPIRATION"
  | "ERR_LICENSE_EXPIRED"
  | "ERR_NODE_LOCK_VIOLATION"
  | "ERR_DOMAIN_LOCK_VIOLATION"
  /** The local clock is earlier than the signed `issued_at` minus the tolerated skew (300 s). */
  | "ERR_CLOCK_BEFORE_ISSUANCE"
  /** The token has a `kid` that is not in the `{ kid: hex }` key map. */
  | "ERR_UNKNOWN_KID"
  /** SDK-only: the runtime has no Web Crypto Ed25519 support. */
  | "ERR_CRYPTO_UNAVAILABLE";

export interface LicensePayload {
  tier: string;
  expires_at?: number | null;
  machine_id?: string | null;
  allowed_domains?: string[] | null;
  features?: string[];
  kid?: string;
  [key: string]: unknown;
}

/**
 * Trusted public keys (64-char hex, 32-byte Ed25519).
 * - a single key:            "0043b5..."
 * - historical keys:         ["new...", "old..."]
 * - keys indexed by key id:  { k2026: "new...", legacy: "old..." }
 * Tokens without `kid` (all tokens issued by KeyForge v1.0) are checked against every key.
 * With a `{ kid: hex }` map, a token with a signed `kid` is checked only against that key
 * (`ERR_UNKNOWN_KID` if the map has no such kid). Strings and arrays have no names: every key is tried.
 */
export type PublicKeys = string | readonly string[] | Readonly<Record<string, string>>;

export interface VerifyOptions {
  /** Unix epoch seconds. Defaults to the current time. */
  now?: number;
  /** Local machine id; required when the token is node-locked, rejected when it is not. */
  machineId?: string;
  /** Caller hostname, enforced when the token has `allowed_domains`. */
  domain?: string;
  /** Custom SubtleCrypto implementation (tests, exotic runtimes). */
  subtle?: SubtleCrypto;
}

export interface VerifyResult {
  valid: boolean;
  payload: LicensePayload | null;
  error: ErrorCode | null;
  /** Key id that verified the signature (key index as string for array input; undefined for a single key). */
  keyId?: string;
}

export interface DecodedToken {
  tier: string;
  payload: unknown;
  payloadBytes: Uint8Array;
  signature: Uint8Array;
}

export interface Verifier {
  verify(token: string, options?: Omit<VerifyOptions, "subtle">): Promise<VerifyResult>;
}

// ---------------------------------------------------------------------------
// Encoding helpers
// ---------------------------------------------------------------------------

/** Tolerated difference (seconds) between the issuer's clock and the local clock for `issued_at`. */
export const CLOCK_SKEW_LEEWAY_SECONDS = 300;

const B64URL_RE = /^[A-Za-z0-9_-]+$/;
const B64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
const B64_LOOKUP: Record<string, number> = {};
for (let i = 0; i < B64_ALPHABET.length; i++) B64_LOOKUP[B64_ALPHABET[i] as string] = i;

/** Strict unpadded base64url decoding (same acceptance rules as the Python reference). */
function b64urlDecode(s: string): Uint8Array {
  if (typeof s !== "string" || !B64URL_RE.test(s) || s.length % 4 === 1) {
    throw new Error("invalid base64url");
  }
  const out = new Uint8Array(Math.floor((s.length * 3) / 4));
  let buf = 0;
  let bits = 0;
  let o = 0;
  for (let i = 0; i < s.length; i++) {
    buf = (buf << 6) | (B64_LOOKUP[s[i] as string] as number);
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[o++] = (buf >> bits) & 0xff;
    }
  }
  return out.subarray(0, o);
}

function hexToBytes(hex: string): Uint8Array | null {
  if (typeof hex !== "string") return null;
  const clean = hex.replace(/\s+/g, "");
  if (!/^[0-9a-fA-F]{64}$/.test(clean)) return null;
  const out = new Uint8Array(32);
  for (let i = 0; i < 32; i++) out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  return out;
}

// ---------------------------------------------------------------------------
// RFC 8032 §5.1.3 strictness checks (parity with the pure-Python reference)
// ---------------------------------------------------------------------------

const P = (1n << 255n) - 19n;
const L = (1n << 252n) + 27742317777372353535851937790883648493n;

function leToBigInt(b: Uint8Array): bigint {
  let n = 0n;
  for (let i = b.length - 1; i >= 0; i--) n = (n << 8n) | BigInt(b[i] as number);
  return n;
}

/** Rejects non-canonical y (y >= p) and the invalid x = 0 / sign = 1 encodings. */
function isCanonicalPoint(enc: Uint8Array): boolean {
  const raw = leToBigInt(enc);
  const y = raw & ((1n << 255n) - 1n);
  const sign = raw >> 255n;
  if (y >= P) return false;
  // x = 0 exactly when y = ±1
  if (sign === 1n && (y === 1n || y === P - 1n)) return false;
  return true;
}

function isStrictSignature(sig: Uint8Array, pk: Uint8Array): boolean {
  if (leToBigInt(sig.subarray(32)) >= L) return false;
  return isCanonicalPoint(sig.subarray(0, 32)) && isCanonicalPoint(pk);
}

// ---------------------------------------------------------------------------
// Domain normalization (parity with _normalize_domain_host)
// ---------------------------------------------------------------------------

const LABEL_RE = /^[a-z0-9-]{1,63}$/;

function toAsciiLabel(label: string): string | null {
  // ASCII fast path; non-ASCII goes through the WHATWG URL IDNA mapping.
  let enc = label;
  if (/[^\x00-\x7f]/.test(label)) {
    try {
      enc = new URL(`http://${label}`).hostname;
    } catch {
      return null;
    }
  }
  enc = enc.toLowerCase();
  if (!LABEL_RE.test(enc) || enc.startsWith("-") || enc.endsWith("-")) return null;
  return enc;
}

function normalizeDomainHost(raw: unknown, allowWildcard: boolean): string | null {
  if (!raw || typeof raw !== "string") return null;
  let s = raw.trim();
  if (!s || /[/\\@?# \t\r\n]/.test(s)) return null;

  let wildcard = false;
  if (s.startsWith("*.")) {
    if (!allowWildcard) return null;
    wildcard = true;
    s = s.slice(2);
  } else if (s.includes("*")) {
    return null;
  }

  const colon = s.lastIndexOf(":");
  if (colon !== -1) {
    const port = s.slice(colon + 1);
    if (!/^\d+$/.test(port)) return null;
    const n = Number(port);
    if (n < 1 || n > 65535) return null;
    s = s.slice(0, colon);
  }

  s = s.replace(/\.+$/, "");
  if (!s || s.startsWith(".") || s.includes("..")) return null;

  const labels = s.split(".");
  if (wildcard && labels.length < 2) return null;

  const ascii: string[] = [];
  for (const label of labels) {
    const enc = toAsciiLabel(label);
    if (!enc) return null;
    ascii.push(enc);
  }
  const normalized = ascii.join(".");
  return wildcard ? `*.${normalized}` : normalized;
}

function matchesAllowedDomains(allowed: readonly string[], domain: string | undefined): boolean {
  if (allowed.length === 0) return true;
  const candidate = normalizeDomainHost(domain, false);
  if (!candidate) return false;
  for (const pattern of allowed) {
    const pat = normalizeDomainHost(pattern, true);
    if (!pat) continue;
    if (pat === candidate) return true;
    if (pat.startsWith("*.")) {
      const suffix = pat.slice(2);
      if (suffix.includes(".") && (candidate === suffix || candidate.endsWith(`.${suffix}`))) return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// Web Crypto access
// ---------------------------------------------------------------------------

let cachedSubtle: Promise<SubtleCrypto | null> | undefined;

async function resolveSubtle(): Promise<SubtleCrypto | null> {
  const g = globalThis as { crypto?: { subtle?: SubtleCrypto } };
  if (g.crypto?.subtle) return g.crypto.subtle;
  // Node.js 18 without --experimental-global-webcrypto
  try {
    const spec = "node:crypto";
    const mod = (await import(/* @vite-ignore */ /* webpackIgnore: true */ spec)) as {
      webcrypto?: { subtle?: SubtleCrypto };
    };
    return mod.webcrypto?.subtle ?? null;
  } catch {
    return null;
  }
}

function getSubtle(custom?: SubtleCrypto): Promise<SubtleCrypto | null> {
  if (custom) return Promise.resolve(custom);
  return (cachedSubtle ??= resolveSubtle());
}

class CryptoUnavailable extends Error {}

// ---------------------------------------------------------------------------
// Key ring
// ---------------------------------------------------------------------------

interface KeyEntry {
  id: string | undefined;
  /** True when the id comes from a `{ kid: hex }` map (binding to `kid` is enforced). */
  named: boolean;
  bytes: Uint8Array;
  imported?: Promise<CryptoKey | null> | undefined;
}

function normalizeKeys(keys: PublicKeys): KeyEntry[] | null {
  let pairs: [string | undefined, unknown][];
  let named = false;
  if (typeof keys === "string") pairs = [[undefined, keys]];
  else if (Array.isArray(keys)) pairs = keys.map((k, i) => [String(i), k]);
  else if (keys && typeof keys === "object") {
    pairs = Object.entries(keys);
    named = true;
  } else return null;
  if (pairs.length === 0) return null;

  const out: KeyEntry[] = [];
  for (const [id, hex] of pairs) {
    const bytes = hexToBytes(hex as string);
    if (!bytes) return null;
    out.push({ id, bytes, named });
  }
  return out;
}

async function importKey(subtle: SubtleCrypto, entry: KeyEntry): Promise<CryptoKey | null> {
  entry.imported ??= subtle
    .importKey("raw", entry.bytes as BufferSource, { name: "Ed25519" }, false, ["verify"])
    .catch((e: unknown) => {
      if (e instanceof Error && e.name === "NotSupportedError") throw new CryptoUnavailable();
      return null; // malformed / off-curve key: never verifies
    });
  try {
    return await entry.imported;
  } catch (e) {
    entry.imported = undefined;
    throw e;
  }
}

function peekKid(payloadBytes: Uint8Array): string | undefined {
  try {
    const p = JSON.parse(new TextDecoder().decode(payloadBytes)) as unknown;
    if (p && typeof p === "object" && !Array.isArray(p)) {
      const kid = (p as Record<string, unknown>).kid;
      if (typeof kid === "string") return kid;
    }
  } catch {
    /* reported after signature verification, like the reference */
  }
  return undefined;
}

async function verifySignature(
  subtle: SubtleCrypto,
  ring: KeyEntry[],
  sig: Uint8Array,
  msg: Uint8Array,
): Promise<KeyEntry | null | "unknown_kid"> {
  const kid = peekKid(msg);
  let ordered = ring;
  if (kid !== undefined && ring[0]?.named) {
    ordered = ring.filter((e) => e.id === kid);
    if (ordered.length === 0) return "unknown_kid";
  }
  for (const entry of ordered) {
    if (!isStrictSignature(sig, entry.bytes)) continue;
    const key = await importKey(subtle, entry);
    if (!key) continue;
    let ok = false;
    try {
      ok = await subtle.verify({ name: "Ed25519" }, key, sig as BufferSource, msg as BufferSource);
    } catch (e) {
      if (e instanceof Error && e.name === "NotSupportedError") throw new CryptoUnavailable();
    }
    if (ok) return entry;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

type Parsed = { ok: true; tier: string; payloadB64: string; sigB64: string } | { ok: false; error: ErrorCode };

function parseToken(token: unknown): Parsed {
  if (!token || typeof token !== "string") return { ok: false, error: "ERR_EMPTY_TOKEN" };
  const parts = token.split(".");
  if (parts.length !== 2) return { ok: false, error: "ERR_INVALID_TOKEN_FORMAT" };
  const [header, sigB64] = parts as [string, string];
  if (!header.startsWith("LIC-")) return { ok: false, error: "ERR_INVALID_TOKEN_PREFIX" };
  const rest = header.slice(4);
  const dash = rest.indexOf("-");
  if (dash === -1) return { ok: false, error: "ERR_INVALID_TOKEN_FORMAT" };
  const tier = rest.slice(0, dash);
  const payloadB64 = rest.slice(dash + 1);
  if (!tier || !payloadB64) return { ok: false, error: "ERR_INVALID_TOKEN_FORMAT" };
  return { ok: true, tier, payloadB64, sigB64 };
}

/** Decodes a token WITHOUT verifying it. Never use the result for authorization. */
export function decodeLicense(token: string): DecodedToken | null {
  const p = parseToken(token);
  if (!p.ok) return null;
  try {
    const payloadBytes = b64urlDecode(p.payloadB64);
    const signature = b64urlDecode(p.sigB64);
    let payload: unknown = null;
    try {
      payload = JSON.parse(new TextDecoder().decode(payloadBytes));
    } catch {
      /* leave null */
    }
    return { tier: p.tier, payload, payloadBytes, signature };
  } catch {
    return null;
  }
}

async function verifyWithRing(
  token: string,
  ring: KeyEntry[] | null,
  options: VerifyOptions,
): Promise<VerifyResult> {
  const fail = (error: ErrorCode, payload: LicensePayload | null = null): VerifyResult => ({
    valid: false,
    payload,
    error,
  });

  // 1. Structure
  const parsed = parseToken(token);
  if (!parsed.ok) return fail(parsed.error);

  // 2. Public keys
  if (!ring) return fail("ERR_INVALID_PUBLIC_KEY");

  // 3. Base64url
  let payloadBytes: Uint8Array;
  let sig: Uint8Array;
  try {
    payloadBytes = b64urlDecode(parsed.payloadB64);
  } catch {
    return fail("ERR_MALFORMED_BASE64_PAYLOAD");
  }
  try {
    sig = b64urlDecode(parsed.sigB64);
  } catch {
    return fail("ERR_MALFORMED_BASE64_SIGNATURE");
  }
  if (sig.length !== 64) return fail("ERR_INVALID_SIGNATURE_LENGTH");

  // 4. Signature
  const subtle = await getSubtle(options.subtle);
  if (!subtle) return fail("ERR_CRYPTO_UNAVAILABLE");
  let matched: KeyEntry | null | "unknown_kid";
  try {
    matched = await verifySignature(subtle, ring, sig, payloadBytes);
  } catch (e) {
    if (e instanceof CryptoUnavailable) return fail("ERR_CRYPTO_UNAVAILABLE");
    throw e;
  }
  if (matched === "unknown_kid") return fail("ERR_UNKNOWN_KID");
  if (!matched) return fail("ERR_SIGNATURE_TAMPERED");

  // 5. JSON payload
  let raw: unknown;
  try {
    raw = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(payloadBytes));
  } catch {
    return fail("ERR_MALFORMED_JSON_PAYLOAD");
  }
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return fail("ERR_INVALID_PAYLOAD_STRUCTURE");
  const payload = raw as LicensePayload;

  // 6. Tier
  if (typeof payload.tier !== "string" || payload.tier.toLowerCase() !== parsed.tier.toLowerCase()) {
    return fail("ERR_TIER_MISMATCH", payload);
  }

  // 7. Expiration
  const now = options.now ?? Math.floor(Date.now() / 1000);
  const exp = payload.expires_at;
  if (exp !== undefined && exp !== null) {
    if (typeof exp !== "number") return fail("ERR_MALFORMED_EXPIRATION", payload);
    if (now > exp) return fail("ERR_LICENSE_EXPIRED", payload);
  }

  // 7b. Clock sanity: local clock earlier than the signed issuance time (beyond tolerated skew)
  const iat = (payload as { issued_at?: unknown }).issued_at;
  if (typeof iat === "number" && now + CLOCK_SKEW_LEEWAY_SECONDS < iat) {
    return fail("ERR_CLOCK_BEFORE_ISSUANCE", payload);
  }

  // 8. Node lock
  const locked = payload.machine_id;
  if (locked !== undefined && locked !== null && typeof locked !== "string") {
    return fail("ERR_INVALID_PAYLOAD_STRUCTURE", payload);
  }
  if (options.machineId !== undefined && typeof options.machineId !== "string") {
    return fail("ERR_NODE_LOCK_VIOLATION", payload);
  }
  const normLocked = typeof locked === "string" && locked.trim() ? locked.trim().toLowerCase() : null;
  const normExpected =
    typeof options.machineId === "string" && options.machineId.trim() ? options.machineId.trim().toLowerCase() : null;
  if (normLocked !== normExpected) return fail("ERR_NODE_LOCK_VIOLATION", payload);

  // 9. Domain lock
  if (options.domain !== undefined && typeof options.domain !== "string") {
    return fail("ERR_DOMAIN_LOCK_VIOLATION", payload);
  }
  const allowed = payload.allowed_domains;
  if (allowed !== undefined && allowed !== null) {
    if (!Array.isArray(allowed) || allowed.some((d) => typeof d !== "string")) {
      return fail("ERR_INVALID_PAYLOAD_STRUCTURE", payload);
    }
    if (allowed.length > 0 && !matchesAllowedDomains(allowed, options.domain)) {
      return fail("ERR_DOMAIN_LOCK_VIOLATION", payload);
    }
  }

  const result: VerifyResult = { valid: true, payload, error: null };
  if (matched.id !== undefined) result.keyId = matched.id;
  return result;
}

/** Verifies a KeyForge license token offline. Never throws for invalid input. */
export function verifyLicense(token: string, publicKeys: PublicKeys, options: VerifyOptions = {}): Promise<VerifyResult> {
  return verifyWithRing(token, normalizeKeys(publicKeys), options);
}

/** Reusable verifier that imports each public key once. Prefer it for repeated checks. */
export function createVerifier(publicKeys: PublicKeys, defaults: VerifyOptions = {}): Verifier {
  const ring = normalizeKeys(publicKeys);
  return {
    verify: (token, options = {}) => verifyWithRing(token, ring, { ...defaults, ...options }),
  };
}
