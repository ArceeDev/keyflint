// KeyFlint: demo en el navegador para keyflint.dev (GitHub Pages).
// Pages no tiene backend, así que este archivo responde a /api/v1/* dentro del navegador:
// genera un par de claves Ed25519 con Web Crypto, firma tokens con el mismo formato que el
// gateway y simula cuotas, activaciones y webhooks en memoria. No envía nada a ningún servidor.
// El gateway real no carga este archivo: su consola habla con la API de verdad.
(() => {
    "use strict";

    const TIERS = {
        community: { seats: 1, credits: 25, recurring: false },
        indie: { seats: 3, credits: 10000, recurring: false },
        agency: { seats: 25, credits: 50000, recurring: false },
        pro: { seats: 3, credits: 500, recurring: true },
        studio: { seats: 25, credits: 5000, recurring: true },
        lifetime: { seats: 3, credits: 10000, recurring: false },
    };
    const KID = "demo-browser";
    const enc = new TextEncoder();
    const licenses = new Map(); // license_key -> record
    const events = [];
    let keysPromise = null;
    let hmacKeyPromise = null;

    const b64url = (bytes) =>
        btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const b64urlToBytes = (s) => {
        const pad = "=".repeat((4 - (s.length % 4)) % 4);
        const raw = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
        return Uint8Array.from(raw, (c) => c.charCodeAt(0));
    };
    const hex = (bytes) => [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
    const nowIso = () => new Date().toISOString();
    const meta = () => ({ request_id: crypto.randomUUID(), timestamp: nowIso(), mode: "browser_demo" });
    const ok = (data, status = 200, headers = {}) => ({ status, body: { success: true, data, metadata: meta() }, headers });
    const fail = (status, code, detail) => ({ status, body: { success: false, error: code, detail, metadata: meta() } });

    function keys() {
        if (!keysPromise) {
            keysPromise = (async () => {
                const pair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
                const raw = await crypto.subtle.exportKey("raw", pair.publicKey);
                return { pair, publicHex: hex(raw) };
            })();
            keysPromise.catch(() => { keysPromise = null; });
        }
        return keysPromise;
    }
    function hmacKey() {
        if (!hmacKeyPromise) {
            hmacKeyPromise = crypto.subtle.generateKey({ name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
        }
        return hmacKeyPromise;
    }

    async function issue({ customer_email, tier, signing_algorithm, allowed_domains }) {
        const t = String(tier || "pro").toLowerCase();
        const spec = TIERS[t];
        if (!spec) return fail(422, "ERR_UNKNOWN_TIER", `Nivel desconocido: ${tier}`);
        const email = String(customer_email || "").trim();
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return fail(422, "ERR_INVALID_EMAIL", "Email no válido.");
        const issued = Math.floor(Date.now() / 1000);
        const payload = {
            license_id: crypto.randomUUID(),
            tier: t,
            customer_email: email,
            max_seats: spec.seats,
            issued_at: issued,
            expires_at: spec.recurring ? issued + 31 * 86400 : null,
            allowed_domains: Array.isArray(allowed_domains) ? allowed_domains : [],
            kid: KID,
        };
        const body = enc.encode(JSON.stringify(payload));
        const algo = signing_algorithm === "hmac-sha256" ? "hmac-sha256" : "ed25519";
        const sig = algo === "ed25519"
            ? await crypto.subtle.sign("Ed25519", (await keys()).pair.privateKey, body)
            : await crypto.subtle.sign("HMAC", await hmacKey(), body);
        const license_key = `LIC-${t.toUpperCase()}-${b64url(body)}.${b64url(sig)}`;
        const rec = {
            license_key, payload, algo, status: "active", balance: spec.credits,
            activations: new Map(), idem: new Set(), created_at: nowIso(),
        };
        licenses.set(license_key, rec);
        log(rec, "license_issued", { tier: t, signing_algorithm: algo });
        return ok({
            license_id: payload.license_id,
            license_key,
            tier: t,
            customer_email: email,
            max_seats: spec.seats,
            quota_credits: spec.credits,
            signing_algorithm: algo,
            expires_at: payload.expires_at ? new Date(payload.expires_at * 1000).toISOString() : null,
            status: "active",
        });
    }

    function log(rec, type, details = {}) {
        events.unshift({ license_key: rec.license_key, event_type: type, details, created_at: nowIso() });
    }

    function find(key) {
        const rec = licenses.get(String(key || "").trim());
        return rec || null;
    }
    const notFound = () => fail(404, "ERR_LICENSE_NOT_FOUND",
        "Token no encontrado. En esta demo solo existen las licencias emitidas en esta página.");

    async function verifySignature(rec) {
        const [p, s] = rec.license_key.split("-").slice(2).join("-").split(".");
        const body = b64urlToBytes(p);
        const sig = b64urlToBytes(s);
        return rec.algo === "ed25519"
            ? crypto.subtle.verify("Ed25519", (await keys()).pair.publicKey, sig, body)
            : crypto.subtle.verify("HMAC", await hmacKey(), sig, body);
    }

    function domainAllowed(list, domain) {
        if (!list.length) return true;
        const d = String(domain || "").trim().toLowerCase();
        if (!d) return false;
        return list.some((raw) => {
            const pat = String(raw).trim().toLowerCase();
            if (pat.startsWith("*.")) return d === pat.slice(2) || d.endsWith(pat.slice(1));
            return d === pat;
        });
    }

    const routes = {
        "GET /api/v1/licenses/public-key": async () => {
            const { publicHex } = await keys();
            return ok({ public_key_hex: publicHex, kid: KID, keys: [{ kid: KID, public_key_hex: publicHex }] });
        },
        "POST /api/v1/licenses/issue": (b) => issue(b),
        "POST /api/v1/licenses/verify": async (b) => {
            const rec = find(b.license_key);
            if (!rec) return notFound();
            if (!(await verifySignature(rec))) return fail(401, "ERR_SIGNATURE_TAMPERED", "Firma no válida.");
            if (rec.status === "revoked") return ok({ valid: false, license_status: "revoked", error: "ERR_LICENSE_REVOKED" });
            if (rec.payload.expires_at && Date.now() / 1000 > rec.payload.expires_at) {
                return ok({ valid: false, license_status: "expired", error: "ERR_LICENSE_EXPIRED" });
            }
            if (!domainAllowed(rec.payload.allowed_domains, b.domain)) {
                return ok({ valid: false, error: "ERR_DOMAIN_LOCK_VIOLATION" });
            }
            if (b.hardware_id && !rec.activations.has(b.hardware_id)) {
                return ok({ valid: false, error: "ERR_NODE_NOT_ACTIVATED" });
            }
            log(rec, "license_verified", { hardware_id: b.hardware_id || null });
            const headers = rec.status === "grace_period" ? { "X-Subscription-Warning": "payment_failed_grace_period" } : {};
            return ok({
                valid: true, license_status: rec.status, tier: rec.payload.tier,
                max_seats: rec.payload.max_seats, current_activations: rec.activations.size,
                credit_balance: rec.balance, signing_algorithm: rec.algo,
            }, 200, headers);
        },
        "POST /api/v1/licenses/activate": async (b) => {
            const rec = find(b.license_key);
            if (!rec) return notFound();
            if (rec.status === "revoked") return fail(403, "ERR_LICENSE_REVOKED", "La licencia está revocada.");
            const hw = String(b.hardware_id || "").trim();
            if (!rec.activations.has(hw) && rec.activations.size >= rec.payload.max_seats) {
                return fail(409, "ERR_SEAT_LIMIT_REACHED", `Límite de ${rec.payload.max_seats} nodos alcanzado.`);
            }
            rec.activations.set(hw, { machine_name: b.machine_name || null, activated_at: nowIso() });
            log(rec, "node_activated", { hardware_id: hw });
            return ok({ activated: true, hardware_id: hw, current_activations: rec.activations.size, max_seats: rec.payload.max_seats });
        },
        "POST /api/v1/licenses/revoke": async (b) => {
            const rec = find(b.license_key);
            if (!rec) return notFound();
            rec.status = "revoked";
            log(rec, "license_revoked", { reason: b.reason || null });
            return ok({ revoked: true, license_status: "revoked" });
        },
        "GET /api/v1/quota/balance": async (_b, q) => {
            const rec = find(q.get("license_key"));
            if (!rec) return notFound();
            return ok({ credit_balance: rec.balance, license_status: rec.status, tier: rec.payload.tier });
        },
        "POST /api/v1/quota/deduct": async (b) => {
            const rec = find(b.license_key);
            if (!rec) return notFound();
            if (rec.status === "revoked") return fail(403, "ERR_LICENSE_REVOKED", "La licencia está revocada.");
            const credits = Number.parseInt(b.credits, 10);
            if (!(credits > 0)) return fail(422, "ERR_INVALID_CREDITS", "Créditos debe ser un entero positivo.");
            if (rec.idem.has(b.idempotency_key)) return ok({ deducted: 0, replayed: true, credit_balance: rec.balance });
            if (rec.balance < credits) {
                return fail(402, "ERR_QUOTA_EXHAUSTED", `Saldo insuficiente: quedan ${rec.balance} créditos.`);
            }
            rec.idem.add(b.idempotency_key);
            rec.balance -= credits;
            log(rec, "quota_deducted", { credits, idempotency_key: b.idempotency_key });
            return ok({ deducted: credits, credit_balance: rec.balance, idempotency_key: b.idempotency_key });
        },
        "POST /api/v1/quota/replenish": async (b) => {
            const rec = find(b.license_key);
            if (!rec) return notFound();
            const credits = Number.parseInt(b.credits, 10);
            if (!(credits > 0)) return fail(422, "ERR_INVALID_CREDITS", "Créditos debe ser un entero positivo.");
            rec.balance += credits;
            log(rec, "quota_replenished", { credits });
            return ok({ replenished: credits, credit_balance: rec.balance });
        },
        "GET /api/v1/telemetry/events": async (_b, q) => {
            const rec = find(q.get("license_key"));
            if (!rec) return notFound();
            const list = events.filter((e) => e.license_key === rec.license_key).map(({ license_key, ...e }) => e);
            return ok({ total: list.length, events: list });
        },
        "POST /api/v1/billing/simulate-webhook": async (b) => {
            const email = String(b.customer_email || "").trim();
            const mine = [...licenses.values()].filter((r) => r.payload.customer_email === email).reverse();
            const latest = mine[0];
            const signature = b.provider === "lemonsqueezy" ? "X-Signature (HMAC-SHA256)" : "Stripe-Signature (t=…,v1=…)";
            switch (b.event_type) {
                case "checkout.session.completed": {
                    const res = await issue({ customer_email: email, tier: b.tier, signing_algorithm: "ed25519" });
                    if (!res.body.success) return res;
                    return ok({ provider: b.provider, event_type: b.event_type, signature_verified: signature,
                        result: { action: "license_issued", ...res.body.data }, license_key: res.body.data.license_key });
                }
                case "invoice.payment_succeeded": {
                    if (!latest) return fail(404, "ERR_NO_SUBSCRIPTION", "Este email no tiene licencias en la demo.");
                    latest.status = "active";
                    latest.balance = TIERS[latest.payload.tier].credits;
                    log(latest, "subscription_renewed");
                    return ok({ provider: b.provider, event_type: b.event_type, signature_verified: signature,
                        result: { action: "quota_replenished", license_key: latest.license_key, credit_balance: latest.balance } });
                }
                case "invoice.payment_failed": {
                    if (!latest) return fail(404, "ERR_NO_SUBSCRIPTION", "Este email no tiene licencias en la demo.");
                    latest.status = "grace_period";
                    log(latest, "payment_failed_grace_period");
                    return ok({ provider: b.provider, event_type: b.event_type, signature_verified: signature,
                        result: { action: "grace_period", license_key: latest.license_key, license_status: "grace_period" } });
                }
                case "customer.subscription.deleted": {
                    if (!latest) return fail(404, "ERR_NO_SUBSCRIPTION", "Este email no tiene licencias en la demo.");
                    latest.status = "revoked";
                    log(latest, "subscription_cancelled");
                    return ok({ provider: b.provider, event_type: b.event_type, signature_verified: signature,
                        result: { action: "license_revoked", license_key: latest.license_key, license_status: "revoked" } });
                }
                default:
                    return fail(422, "ERR_UNSUPPORTED_EVENT", `Evento no soportado: ${b.event_type}`);
            }
        },
        "POST /api/v1/billing/portal/lookup": async (b) => {
            const q = String(b.query || "").trim();
            const found = q.startsWith("LIC-")
                ? [find(q)].filter(Boolean)
                : [...licenses.values()].filter((r) => r.payload.customer_email.toLowerCase() === q.toLowerCase());
            if (!found.length) {
                return fail(404, "ERR_LICENSE_NOT_FOUND",
                    "No hay licencias de la demo para esa consulta. Emite una en la consola de arriba y vuelve a probar.");
            }
            const { publicHex } = await keys();
            return ok({
                customer_email: found[0].payload.customer_email,
                total_licenses: found.length,
                public_key_hex: publicHex,
                licenses: found.map((r) => ({
                    tier: r.payload.tier, status: r.status, license_key: r.license_key, credit_balance: r.balance,
                    current_activations: r.activations.size, max_seats: r.payload.max_seats,
                    expires_at: r.payload.expires_at ? new Date(r.payload.expires_at * 1000).toISOString() : null,
                })),
                python_snippet: `from keyflint_verify import validate_offline\n\nis_valid, payload, err = validate_offline(\n    license_token="${found[0].license_key.slice(0, 24)}...",\n    public_key_hex="${publicHex}",\n)`,
                typescript_snippet: `import { verifyLicense } from "keyflint-verify";\n\nconst { valid, payload } = await verifyLicense(token, "${publicHex}");`,
            });
        },
    };

    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (input, init = {}) => {
        const url = new URL(typeof input === "string" ? input : input.url, window.location.href);
        if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/v1/")) {
            return nativeFetch(input, init);
        }
        const method = String(init.method || "GET").toUpperCase();
        const handler = routes[`${method} ${url.pathname}`];
        let out;
        try {
            const body = init.body ? JSON.parse(init.body) : {};
            out = handler
                ? await handler(body, url.searchParams)
                : fail(404, "ERR_NOT_AVAILABLE_IN_DEMO", "Este endpoint solo existe en el gateway desplegado.");
        } catch (err) {
            const unsupported = err && /Ed25519|not supported|NotSupported/i.test(`${err.name} ${err.message}`);
            out = fail(500, unsupported ? "ERR_BROWSER_NO_ED25519" : "ERR_DEMO",
                unsupported ? "Tu navegador no soporta Ed25519 en Web Crypto. Prueba con una versión reciente de Chrome, Firefox o Safari."
                    : String(err && err.message));
        }
        return new Response(JSON.stringify(out.body), {
            status: out.status,
            headers: { "Content-Type": "application/json", ...(out.headers || {}) },
        });
    };
})();
