/**
 * keyforge-verify/mcp — license gating and credit metering for MCP tool handlers.
 *
 *   import { createKeyForge } from "keyforge-verify/mcp";
 *   const kf = createKeyForge();                                  // reads KEYFORGE_* env vars
 *   server.registerTool("search", cfg, kf.requireLicense(async (args) => ...));   // offline
 *   server.registerTool("summarize", cfg, kf.metered(5, async (args) => ...));    // + /quota/deduct
 *
 * Works with any handler shape (`McpServer.registerTool`, `server.tool`, low-level
 * `setRequestHandler`), because the wrappers keep the handler's arguments and return type.
 * Failures throw `KeyForgeMcpError`, which has the same shape as the SDK's McpError
 * (`code`, `message`, `data`) and the same JSON-RPC codes as the Python package.
 */

import { decodeLicense, verifyLicense, type PublicKeys, type VerifyResult } from "./index.js";

export const LICENSE_INVALID = -32040;
export const FEATURE_NOT_ENTITLED = -32041;
export const QUOTA_EXHAUSTED = -32042;
export const GATEWAY_ERROR = -32043;

export interface KeyForgeErrorData {
  reason: string;
  status?: number;
  checkoutUrl?: string;
  missingFeatures?: string[];
  tier?: string;
  [key: string]: unknown;
}

export class KeyForgeMcpError extends Error {
  readonly code: number;
  readonly data: KeyForgeErrorData;
  constructor(code: number, message: string, data: KeyForgeErrorData) {
    super(message);
    this.name = "McpError";
    this.code = code;
    this.data = data;
  }
  get reason(): string {
    return this.data.reason;
  }
}

export interface KeyForgeOptions {
  /** License token. Default: KEYFORGE_LICENSE. */
  licenseKey?: string;
  /** Trusted public key(s). Default: KEYFORGE_PUBLIC_KEYS (hex, comma list, or kid=hex pairs). */
  publicKeys?: PublicKeys;
  /** Gateway base URL, required for `metered`. Default: KEYFORGE_URL. */
  gatewayUrl?: string;
  /** Machine id for node-locked licenses. Default: KEYFORGE_MACHINE_ID. */
  machineId?: string;
  /** Caller domain for domain-locked licenses. Default: KEYFORGE_DOMAIN. */
  domain?: string;
  /** Upgrade link added to quota errors. Default: KEYFORGE_CHECKOUT_URL. */
  checkoutUrl?: string;
  /** Per-request timeout in ms (default 5000). */
  timeoutMs?: number;
  /** Default event_type sent to the gateway (default "mcp_tool_call"). */
  eventType?: string;
  /** Custom fetch (tests, proxies). Default: global fetch. */
  fetch?: typeof fetch;
}

export interface DeductOptions {
  idempotencyKey?: string;
  eventType?: string;
  metadata?: Record<string, unknown>;
}

export interface GateOptions {
  features?: string[];
}

export interface MeteredOptions extends GateOptions {
  eventType?: string;
  /** Give the credits back (POST /quota/refund) if the handler throws or returns { isError: true }. Default true. */
  refundOnError?: boolean;
}

type AnyFn = (...args: never[]) => unknown;
type Wrapped<F extends AnyFn> = (...args: Parameters<F>) => Promise<Awaited<ReturnType<F>>>;

export interface KeyForge {
  /** Offline license check (cached for up to 60 s). Throws KeyForgeMcpError. */
  check(options?: GateOptions): Promise<VerifyResult>;
  /** POST /api/v1/quota/deduct with an automatic idempotency key. Throws KeyForgeMcpError. */
  deduct(credits?: number, options?: DeductOptions): Promise<Record<string, unknown>>;
  /** Best-effort POST /api/v1/quota/refund for a previous deduct. Never throws; resolves true on success. */
  refund(idempotencyKey: string, reason?: string): Promise<boolean>;
  requireLicense<F extends AnyFn>(handler: F, options?: GateOptions): Wrapped<F>;
  metered<F extends AnyFn>(credits: number, handler: F, options?: MeteredOptions): Wrapped<F>;
}

function env(name: string): string | undefined {
  const p = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  const v = p?.env?.[name];
  return v && v.trim() ? v.trim() : undefined;
}

function parseKeysEnv(raw: string | undefined): PublicKeys {
  const items = (raw ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  if (items.length && items.every((s) => s.includes("="))) {
    return Object.fromEntries(items.map((s) => [s.slice(0, s.indexOf("=")).trim(), s.slice(s.indexOf("=") + 1).trim()]));
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

export function createKeyForge(options: KeyForgeOptions = {}): KeyForge {
  const licenseKey = options.licenseKey ?? env("KEYFORGE_LICENSE") ?? "";
  const publicKeys = options.publicKeys ?? parseKeysEnv(env("KEYFORGE_PUBLIC_KEYS") ?? env("KEYFORGE_PUBLIC_KEY"));
  const gatewayUrl = (options.gatewayUrl ?? env("KEYFORGE_URL") ?? "").replace(/\/+$/, "");
  const machineId = options.machineId ?? env("KEYFORGE_MACHINE_ID");
  const domain = options.domain ?? env("KEYFORGE_DOMAIN");
  const checkoutUrl = options.checkoutUrl ?? env("KEYFORGE_CHECKOUT_URL");
  const timeoutMs = options.timeoutMs ?? 5000;
  const defaultEvent = options.eventType ?? "mcp_tool_call";
  const doFetch = options.fetch ?? (globalThis.fetch as typeof fetch | undefined);

  let cached: VerifyResult | undefined;
  let cachedUntil = 0;

  const fail = (code: number, message: string, data: { reason: string; [k: string]: unknown }): never => {
    throw new KeyForgeMcpError(code, message, strip(data) as KeyForgeErrorData);
  };

  async function check(gate: GateOptions = {}): Promise<VerifyResult> {
    const now = Date.now() / 1000;
    if (!cached || now >= cachedUntil) {
      const opts: { machineId?: string; domain?: string } = {};
      if (machineId !== undefined) opts.machineId = machineId;
      if (domain !== undefined) opts.domain = domain;
      const r = await verifyLicense(licenseKey, publicKeys, opts);
      if (!r.valid) {
        fail(LICENSE_INVALID, `KeyForge license rejected: ${r.error}.`, { reason: r.error ?? "ERR_LICENSE_INVALID", checkoutUrl });
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
        fail(FEATURE_NOT_ENTITLED, `This tool requires the feature(s) ${missing.join(", ")}, which your plan does not include.`, {
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
    if (!gatewayUrl) fail(GATEWAY_ERROR, "KEYFORGE_URL is not set; metered tools need the gateway.", { reason: "GATEWAY_NOT_CONFIGURED" });
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
          signal: AbortSignal.timeout(timeoutMs),
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
        fail(QUOTA_EXHAUSTED, `Credits exhausted for this license.${checkoutUrl ? ` Upgrade or top up here: ${checkoutUrl}` : ""}`, {
          reason: "QUOTA_EXHAUSTED",
          status: 402,
          checkoutUrl,
        });
      }
      if (res.status === 401 || res.status === 403 || res.status === 404) {
        fail(LICENSE_INVALID, `KeyForge license rejected: ${message}`, { reason: code, status: res.status, checkoutUrl });
      }
      fail(GATEWAY_ERROR, `KeyForge gateway error: ${message}`, { reason: code, status: res.status });
    }
    return fail(GATEWAY_ERROR, `KeyForge gateway unreachable: ${String(lastErr)}.`, { reason: "GATEWAY_UNREACHABLE" });
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

  return {
    check,
    deduct,
    refund,
    requireLicense(handler, gate = {}) {
      return (async (...args) => {
        await check(gate);
        return (await handler(...args)) as never;
      }) as Wrapped<typeof handler>;
    },
    metered(credits, handler, opts = {}) {
      if (!Number.isInteger(credits) || credits <= 0) throw new RangeError("credits must be a positive integer");
      const eventType = opts.eventType ?? (handler.name ? `mcp:${handler.name}` : defaultEvent);
      return (async (...args) => {
        await check(opts);
        const idempotencyKey = randomKey();
        await deduct(credits, { eventType, idempotencyKey });
        if (opts.refundOnError === false) return (await handler(...args)) as never;
        let out: unknown;
        try {
          out = await handler(...args);
        } catch (e) {
          await refund(idempotencyKey, "tool_error");
          throw e;
        }
        if (out && typeof out === "object" && (out as { isError?: unknown }).isError === true) {
          await refund(idempotencyKey, "tool_error_result");
        }
        return out as never;
      }) as Wrapped<typeof handler>;
    },
  };
}

/** Unverified view of the configured token (display only). */
export { decodeLicense };
