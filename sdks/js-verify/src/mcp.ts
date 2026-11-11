/**
 * keyflint-verify/mcp — license gating and credit metering for MCP tool handlers.
 *
 *   import { createKeyFlint } from "keyflint-verify/mcp";
 *   const kf = createKeyFlint();                                  // reads KEYFLINT_* env vars
 *   server.registerTool("search", cfg, kf.requireLicense(async (args) => ...));   // offline
 *   server.registerTool("summarize", cfg, kf.metered(5, async (args) => ...));    // + /quota/deduct
 *
 * Works with any handler shape (`McpServer.registerTool`, `server.tool`, low-level
 * `setRequestHandler`), because the wrappers keep the handler's arguments and return type.
 * Failures throw `KeyFlintMcpError`, which has the same shape as the SDK's McpError
 * (`code`, `message`, `data`) and the same JSON-RPC codes as the Python package.
 */

import { decodeLicense, verifyLicense, type PublicKeys, type VerifyResult } from "./index.js";
import { createClockGuard, stableMachineId, type ClockGuard } from "./node.js";

export { createClockGuard, stableMachineId, type ClockGuard };

// JSON-RPC server error range, same values as the Python package. -32042 is avoided because
// MCP itself uses it for URLElicitationRequired.
export const LICENSE_INVALID = -32060;
export const FEATURE_NOT_ENTITLED = -32061;
export const QUOTA_EXHAUSTED = -32062;
export const GATEWAY_ERROR = -32063;
/** Hard cap for `offlineGraceCalls`: calls that may run unpaid while the gateway is down. */
export const MAX_OFFLINE_GRACE_CALLS = 5;
/** Default result cache TTL (ms) for retries sharing an `idempotencyKey`. */
export const DEFAULT_DEDUP_TTL_MS = 300_000;
const MAX_DEDUP_ENTRIES = 1024;
const TRANSIENT_STATUSES = new Set([502, 503, 504]);

const LICENSE_MESSAGES: Record<string, string> = {
  ERR_EMPTY_TOKEN: "No KeyFlint license is configured. Set KEYFLINT_LICENSE.",
  ERR_SIGNATURE_TAMPERED:
    "This license was not issued for this server (signature check failed). Check KEYFLINT_LICENSE and KEYFLINT_PUBLIC_KEYS.",
  ERR_UNKNOWN_KID: "This license was signed with a key this server does not trust. Check KEYFLINT_PUBLIC_KEYS.",
  ERR_NODE_LOCK_VIOLATION: "This license is locked to another machine.",
  ERR_DOMAIN_LOCK_VIOLATION: "This license is not valid for this domain.",
  ERR_CLOCK_BEFORE_ISSUANCE: "The system clock is earlier than the license issue date. Correct the clock and retry.",
  ERR_CLOCK_ROLLBACK_DETECTED:
    "The system clock is behind the last time this license was checked on this machine. Correct the clock and retry.",
};
const NO_CHECKOUT_HINT = new Set(["ERR_CLOCK_BEFORE_ISSUANCE", "ERR_CLOCK_ROLLBACK_DETECTED", "ERR_UNKNOWN_KID", "ERR_SIGNATURE_TAMPERED"]);

/** Plain-language reason plus the next step; this text is what MCP clients show. */
function licenseMessage(error: string | null, payload: VerifyResult["payload"], checkoutUrl?: string): string {
  const code = error ?? "ERR_LICENSE_INVALID";
  let text: string;
  if (code === "ERR_LICENSE_EXPIRED") {
    const exp = payload?.expires_at;
    text = typeof exp === "number"
      ? `Your license expired on ${new Date(exp * 1000).toISOString().slice(0, 10)}.`
      : "Your license has expired.";
  } else {
    text = LICENSE_MESSAGES[code] ?? `The KeyFlint license is invalid (${code}).`;
  }
  if (checkoutUrl && !NO_CHECKOUT_HINT.has(code)) text += ` Get or renew a license: ${checkoutUrl}`;
  return text;
}

export interface KeyFlintErrorData {
  reason: string;
  status?: number;
  checkoutUrl?: string;
  missingFeatures?: string[];
  tier?: string;
  [key: string]: unknown;
}

export class KeyFlintMcpError extends Error {
  readonly code: number;
  readonly data: KeyFlintErrorData;
  constructor(code: number, message: string, data: KeyFlintErrorData) {
    super(message);
    this.name = "McpError";
    this.code = code;
    this.data = data;
  }
  get reason(): string {
    return this.data.reason;
  }
}

export interface KeyFlintOptions {
  /** License token. Default: KEYFLINT_LICENSE. */
  licenseKey?: string;
  /** Trusted public key(s). Default: KEYFLINT_PUBLIC_KEYS (hex, comma list, or kid=hex pairs). */
  publicKeys?: PublicKeys;
  /** Gateway base URL, required for `metered`. Default: KEYFLINT_URL. */
  gatewayUrl?: string;
  /** Machine id for node-locked licenses. Default: KEYFLINT_MACHINE_ID. */
  machineId?: string;
  /** Caller domain for domain-locked licenses. Default: KEYFLINT_DOMAIN. */
  domain?: string;
  /** Upgrade link added to quota errors. Default: KEYFLINT_CHECKOUT_URL. */
  checkoutUrl?: string;
  /** Per-request timeout in ms (default 5000). */
  timeoutMs?: number;
  /** Default event_type sent to the gateway (default "mcp_tool_call"). */
  eventType?: string;
  /** Custom fetch (tests, proxies). Default: global fetch. */
  fetch?: typeof fetch;
  /**
   * v1.2: reject clocks set back below the latest time seen (expiring licenses only).
   * Default true (file `~/.keyflint/clock_state`, `KEYFLINT_CLOCK_STATE=off` for memory only).
   */
  clockGuard?: boolean | ClockGuard;
}

export interface DeductOptions {
  idempotencyKey?: string;
  eventType?: string;
  metadata?: Record<string, unknown>;
  /** Per-call timeout in ms (default: the instance's timeoutMs). */
  timeoutMs?: number;
}

export interface GateOptions {
  features?: string[];
}

export interface MeteredOptions<F extends AnyFn = AnyFn> extends GateOptions {
  eventType?: string;
  /** Give the credits back (POST /quota/refund) if the handler throws or returns { isError: true }. Default true. */
  refundOnError?: boolean;
  /**
   * v1.2, opt-in (default 0, max 5 per instance): when the gateway is unreachable within `timeoutMs`
   * (or answers 502/503/504) but the license verified offline, up to N calls run anyway. Their debits
   * are queued in memory and replayed with the same idempotency key before the next successful debit.
   * Queued debits are never refunded and are lost if the process exits first.
   */
  offlineGraceCalls?: number;
  /** Deduct timeout for this tool in ms (default: the instance's timeoutMs). */
  timeoutMs?: number;
  /**
   * Derives a retry-stable request id from handler arguments. When it returns a non-empty string,
   * `/quota/deduct` receives a deterministic key and (when `dedupTtlMs > 0`) successful non-error
   * outputs are cached locally with single-flight coalescing so client retries replay the first result
   * without a second deduct or execution.
   */
  idempotencyKey?: (...args: Parameters<F>) => string | undefined | null;
  /** How long (ms) successful results for an `idempotencyKey` are cached for retries (default 300_000; 0 disables). */
  dedupTtlMs?: number;
}

type AnyFn = (...args: never[]) => unknown;
type Wrapped<F extends AnyFn> = (...args: Parameters<F>) => Promise<Awaited<ReturnType<F>>>;

export interface KeyFlint {
  /** Offline license check (cached for up to 60 s). Throws KeyFlintMcpError. */
  check(options?: GateOptions): Promise<VerifyResult>;
  /** POST /api/v1/quota/deduct with an automatic idempotency key. Throws KeyFlintMcpError. */
  deduct(credits?: number, options?: DeductOptions): Promise<Record<string, unknown>>;
  /** Best-effort POST /api/v1/quota/refund for a previous deduct. Never throws; resolves true on success. */
  refund(idempotencyKey: string, reason?: string): Promise<boolean>;
  /** Replays debits of calls that ran on offline grace; resolves how many were sent. */
  flushPending(): Promise<number>;
  /** Calls that ran on offline grace and are not yet debited. */
  readonly pendingDebits: number;
  requireLicense<F extends AnyFn>(handler: F, options?: GateOptions): Wrapped<F>;
  metered<F extends AnyFn>(credits: number, handler: F, options?: MeteredOptions<F>): Wrapped<F>;
}

function env(name: string): string | undefined {
  const p = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  // KEYFORGE_* (pre-rename) is accepted as a fallback for every KEYFLINT_* variable.
  const legacy = name.startsWith("KEYFLINT_") ? "KEYFORGE_" + name.slice(9) : undefined;
  for (const n of legacy ? [name, legacy] : [name]) {
    const v = p?.env?.[n];
    if (v && v.trim()) return v.trim();
  }
  return undefined;
}

/** Parses `hex`, `hex,hex` or `kid=hex` entries; bare keys in a named list become `legacy-<i>`. */
export function parseKeysEnv(raw: string | undefined): PublicKeys {
  const items = (raw ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  if (items.some((s) => s.includes("="))) {
    return Object.fromEntries(
      items.map((s, i) => {
        const at = s.lastIndexOf("=");
        return [(at > 0 ? s.slice(0, at).trim() : "") || `legacy-${i}`, s.slice(at + 1).trim()];
      }),
    );
  }
  return items.length === 1 ? (items[0] as string) : items;
}

function randomKey(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string; getRandomValues?: (a: Uint8Array) => Uint8Array } })
    .crypto;
  if (c?.randomUUID) return `mcp-${c.randomUUID()}`;
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256);
  return `mcp-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

function strip<T extends Record<string, unknown>>(o: T): T {
  for (const k of Object.keys(o)) if (o[k] === undefined) delete o[k];
  return o;
}

function isErrorResult(out: unknown): boolean {
  return Boolean(out && typeof out === "object" && (out as { isError?: unknown }).isError === true);
}

async function normalizeGatewayKey(scope: string, raw: unknown): Promise<{ rawKey: string; gwKey: string } | undefined> {
  if (typeof raw !== "string") return undefined;
  const stripped = raw.trim();
  if (!stripped) return undefined;
  const scoped = `${scope}:${stripped}`;
  if (!scoped.startsWith("refund:") && scoped.length <= 200) {
    return { rawKey: stripped, gwKey: scoped };
  }
  const subtle = (globalThis as { crypto?: Crypto }).crypto?.subtle;
  if (subtle) {
    const digest = await subtle.digest("SHA-256", new TextEncoder().encode(scoped));
    const hex = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
    return { rawKey: stripped, gwKey: `mcp-req-${hex}` };
  }
  let h1 = 0x811c9dc5;
  let h2 = 0x811c9dc5;
  for (let i = 0; i < scoped.length; i++) {
    const c = scoped.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ (c + i), 0x01000193) >>> 0;
  }
  return { rawKey: stripped, gwKey: `mcp-req-${h1.toString(16).padStart(8, "0")}${h2.toString(16).padStart(8, "0")}` };
}

export function createKeyFlint(options: KeyFlintOptions = {}): KeyFlint {
  const licenseKey = options.licenseKey ?? env("KEYFLINT_LICENSE") ?? "";
  const publicKeys = options.publicKeys ?? parseKeysEnv(env("KEYFLINT_PUBLIC_KEYS") ?? env("KEYFLINT_PUBLIC_KEY"));
  const gatewayUrl = (options.gatewayUrl ?? env("KEYFLINT_URL") ?? "").replace(/\/+$/, "");
  const machineId = options.machineId ?? env("KEYFLINT_MACHINE_ID");
  const domain = options.domain ?? env("KEYFLINT_DOMAIN");
  const checkoutUrl = options.checkoutUrl ?? env("KEYFLINT_CHECKOUT_URL");
  const timeoutMs = options.timeoutMs ?? 5000;
  const defaultEvent = options.eventType ?? "mcp_tool_call";
  const doFetch = options.fetch ?? (globalThis.fetch as typeof fetch | undefined);

  const guard: ClockGuard | undefined =
    options.clockGuard === false ? undefined : options.clockGuard === true || options.clockGuard === undefined
      ? createClockGuard() : options.clockGuard;
  const decoded = decodeLicense(licenseKey)?.payload as { expires_at?: unknown; machine_id?: unknown } | null | undefined;
  const expiring = decoded?.expires_at !== undefined && decoded?.expires_at !== null;
  const strategy = (env("KEYFLINT_MACHINE_ID_STRATEGY") ?? "").toLowerCase();
  let resolvedMachineId: Promise<string | undefined> | undefined;
  const machineIdFor = (): Promise<string | undefined> =>
    (resolvedMachineId ??= machineId !== undefined || strategy !== "stable" || !decoded?.machine_id
      ? Promise.resolve(machineId)
      : stableMachineId());

  let cached: VerifyResult | undefined;
  let cachedUntil = 0;

  const fail = (code: number, message: string, data: { reason: string; [k: string]: unknown }): never => {
    throw new KeyFlintMcpError(code, message, strip(data) as KeyFlintErrorData);
  };

  async function check(gate: GateOptions = {}): Promise<VerifyResult> {
    const now = Date.now() / 1000;
    if (!cached || now >= cachedUntil) {
      const opts: { machineId?: string; domain?: string; lastSeen?: number } = {};
      const mid = await machineIdFor();
      if (mid !== undefined) opts.machineId = mid;
      if (domain !== undefined) opts.domain = domain;
      const useGuard = guard !== undefined && expiring;
      const last = useGuard ? await guard.lastSeen() : undefined;
      if (last !== undefined) opts.lastSeen = last;
      const r = await verifyLicense(licenseKey, publicKeys, opts);
      if (r.valid && useGuard) await guard.record(now);
      if (!r.valid) {
        fail(LICENSE_INVALID, licenseMessage(r.error, r.payload, checkoutUrl), { reason: r.error ?? "ERR_LICENSE_INVALID", checkoutUrl });
      }
      const exp = r.payload?.expires_at;
      cached = r;
      cachedUntil = now + (typeof exp === "number" ? Math.max(0, Math.min(60, exp - now)) : 60);
    }
    const result = cached as VerifyResult;
    if (gate.features?.length) {
      const have = new Set(Array.isArray(result.payload?.features) ? result.payload.features : []);
      const missing = gate.features.filter((f) => !have.has(f));
      if (missing.length) {
        const tier = result.payload?.tier || "current";
        const text = `This tool requires the feature(s) ${missing.join(", ")}, which the ${tier} plan does not include.`;
        fail(FEATURE_NOT_ENTITLED, checkoutUrl ? `${text} Upgrade: ${checkoutUrl}` : text, {
          reason: "FEATURE_NOT_ENTITLED",
          missingFeatures: missing,
          tier: result.payload?.tier,
          checkoutUrl,
        });
      }
    }
    return result;
  }

  async function deduct(credits = 1, opts: DeductOptions = {}): Promise<Record<string, unknown>> {
    if (!gatewayUrl) fail(GATEWAY_ERROR, "KEYFLINT_URL is not set; metered tools need the gateway.", { reason: "GATEWAY_NOT_CONFIGURED" });
    if (!doFetch) fail(GATEWAY_ERROR, "No fetch implementation available.", { reason: "GATEWAY_NOT_CONFIGURED" });
    const key = opts.idempotencyKey ?? randomKey();
    const body = JSON.stringify(
      strip({ license_key: licenseKey, credits, idempotency_key: key, event_type: opts.eventType ?? defaultEvent, metadata: opts.metadata }),
    );
    let lastErr: unknown;
    for (let attempt = 0; attempt < 2; attempt++) {
      let res: Response;
      try {
        res = await (doFetch as typeof fetch)(`${gatewayUrl}/api/v1/quota/deduct`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json", "Idempotency-Key": key },
          body,
          signal: AbortSignal.timeout(opts.timeoutMs ?? timeoutMs),
        });
      } catch (e) {
        lastErr = e; // network error: retry once with the same idempotency key
        continue;
      }
      let json: { data?: Record<string, unknown>; error?: { code?: string; message?: string; details?: unknown } } = {};
      try {
        json = (await res.json()) as typeof json;
      } catch {
        /* non-JSON body */
      }
      if (res.ok) return json.data ?? (json as Record<string, unknown>);
      const code = json.error?.code ?? `HTTP_${res.status}`;
      const message = json.error?.message ?? `Gateway returned HTTP ${res.status}.`;
      if (res.status === 402 || code === "QUOTA_EXHAUSTED") {
        const det = (json.error?.details ?? {}) as { requested_credits?: unknown; remaining_credits?: unknown };
        const need = det.requested_credits;
        const left = det.remaining_credits;
        let text = typeof need === "number" && typeof left === "number"
          ? `Credits exhausted: this tool needs ${need} credits and the license has ${left} left.`
          : "Credits exhausted for this license.";
        if (checkoutUrl) text += ` Top up: ${checkoutUrl}`;
        fail(QUOTA_EXHAUSTED, `${text} The tool did not run and no credits were charged.`, {
          reason: "QUOTA_EXHAUSTED",
          status: 402,
          checkoutUrl,
        });
      }
      if (res.status === 401 || res.status === 403 || res.status === 404) {
        fail(LICENSE_INVALID, `KeyFlint license rejected: ${message}`, { reason: code, status: res.status, checkoutUrl });
      }
      fail(GATEWAY_ERROR, `KeyFlint gateway error: ${message} The tool did not run.`, { reason: code, status: res.status });
    }
    return fail(
      GATEWAY_ERROR,
      `Could not reach the KeyFlint license server at ${gatewayUrl} (${String(lastErr)}). The tool did not run.`,
      { reason: "GATEWAY_UNREACHABLE" },
    );
  }

  async function refund(idempotencyKey: string, reason?: string): Promise<boolean> {
    if (!gatewayUrl || !doFetch) return false;
    try {
      const res = await (doFetch as typeof fetch)(`${gatewayUrl}/api/v1/quota/refund`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(strip({ license_key: licenseKey, idempotency_key: idempotencyKey, reason })),
        signal: AbortSignal.timeout(timeoutMs),
      });
      return res.ok;
    } catch {
      return false;
    }
  }

  type Pending = { key: string; credits: number; eventType: string };
  const pending: Pending[] = [];
  const dedupCache = new Map<string, { expiresAt: number; value: unknown }>();
  const dedupInflight = new Map<string, Promise<unknown>>();
  let handlerSeq = 0;

  const getCached = (key: string): { value: unknown } | undefined => {
    const hit = dedupCache.get(key);
    if (!hit) return undefined;
    if (hit.expiresAt <= Date.now()) {
      dedupCache.delete(key);
      return undefined;
    }
    return hit;
  };
  const setCached = (key: string, value: unknown, ttlMs: number): void => {
    const now = Date.now();
    dedupCache.delete(key);
    if (dedupCache.size >= MAX_DEDUP_ENTRIES) {
      for (const [k, entry] of dedupCache) if (entry.expiresAt <= now) dedupCache.delete(k);
      while (dedupCache.size >= MAX_DEDUP_ENTRIES) {
        const oldest = dedupCache.keys().next().value;
        if (oldest === undefined) break;
        dedupCache.delete(oldest);
      }
    }
    dedupCache.set(key, { expiresAt: now + ttlMs, value });
  };

  const isTransient = (e: unknown): boolean =>
    e instanceof KeyFlintMcpError &&
    (e.data.reason === "GATEWAY_UNREACHABLE" || (typeof e.data.status === "number" && TRANSIENT_STATUSES.has(e.data.status)));

  async function flushPending(): Promise<number> {
    let sent = 0;
    while (pending.length) {
      const entry = pending[0] as Pending;
      try {
        await deduct(entry.credits, { idempotencyKey: entry.key, eventType: entry.eventType, metadata: { offline_grace: true } });
      } catch (e) {
        if (isTransient(e)) return sent;
        // Refused (e.g. 402): the call was served on grace; drop it.
      }
      if (pending[0] === entry) pending.shift();
      sent++;
    }
    return sent;
  }

  return {
    check,
    deduct,
    refund,
    flushPending,
    get pendingDebits() {
      return pending.length;
    },
    requireLicense(handler, gate = {}) {
      return (async (...args) => {
        await check(gate);
        return (await handler(...args)) as never;
      }) as Wrapped<typeof handler>;
    },
    metered(credits, handler, opts = {}) {
      if (!Number.isInteger(credits) || credits <= 0) throw new RangeError("credits must be a positive integer");
      const grace = opts.offlineGraceCalls ?? 0;
      if (!Number.isInteger(grace) || grace < 0 || grace > MAX_OFFLINE_GRACE_CALLS) {
        throw new RangeError(`offlineGraceCalls must be an integer between 0 and ${MAX_OFFLINE_GRACE_CALLS}`);
      }
      const dedupTtlMs = opts.dedupTtlMs ?? DEFAULT_DEDUP_TTL_MS;
      if (typeof dedupTtlMs !== "number" || !Number.isFinite(dedupTtlMs) || dedupTtlMs < 0) {
        throw new RangeError("dedupTtlMs must be a non-negative finite number");
      }
      const toolId = ++handlerSeq;
      const eventType = opts.eventType ?? (handler.name ? `mcp:${handler.name}` : defaultEvent);
      return (async (...args) => {
        await check(opts);
        const derived = opts.idempotencyKey ? await normalizeGatewayKey(eventType, opts.idempotencyKey(...args)) : undefined;
        const idempotencyKey = derived?.gwKey ?? randomKey();
        const cacheKey = derived && dedupTtlMs > 0
          ? JSON.stringify([licenseKey, toolId, eventType, derived.rawKey])
          : undefined;

        if (cacheKey !== undefined) {
          const hit = getCached(cacheKey);
          if (hit) return hit.value as never;
          const running = dedupInflight.get(cacheKey);
          if (running) return (await running) as never;
        }

        const executeAttempt = async (): Promise<unknown> => {
          if (pending.length) await flushPending();
          try {
            const d: DeductOptions = { eventType, idempotencyKey };
            if (opts.timeoutMs !== undefined) d.timeoutMs = opts.timeoutMs;
            await deduct(credits, d);
          } catch (e) {
            if (grace > 0 && isTransient(e) && pending.length < grace) {
              pending.push({ key: idempotencyKey, credits, eventType });
              const graceOut = await handler(...args); // offline grace: never refunded
              if (cacheKey !== undefined && !isErrorResult(graceOut)) setCached(cacheKey, graceOut, dedupTtlMs);
              return graceOut;
            }
            throw e;
          }
          if (opts.refundOnError === false) {
            const out = await handler(...args);
            if (cacheKey !== undefined && !isErrorResult(out)) setCached(cacheKey, out, dedupTtlMs);
            return out;
          }
          let out: unknown;
          try {
            out = await handler(...args);
          } catch (e) {
            await refund(idempotencyKey, "tool_error");
            throw e;
          }
          const isErr = isErrorResult(out);
          if (isErr) {
            await refund(idempotencyKey, "tool_error_result");
          } else if (cacheKey !== undefined) {
            setCached(cacheKey, out, dedupTtlMs);
          }
          return out;
        };

        if (cacheKey === undefined) return (await executeAttempt()) as never;
        const run = executeAttempt().finally(() => {
          if (dedupInflight.get(cacheKey) === run) dedupInflight.delete(cacheKey);
        });
        dedupInflight.set(cacheKey, run);
        return (await run) as never;
      }) as Wrapped<typeof handler>;
    },
  };
}

/** Unverified view of the configured token (display only). */
export { decodeLicense };
