// KeyFlint v1.2.0 — Consola operativa

document.addEventListener("DOMContentLoaded", () => {
    const issueEmail = document.getElementById("issueEmail");
    const issueTier = document.getElementById("issueTier");
    const issueAlgo = document.getElementById("issueAlgo");
    const issueDomain = document.getElementById("issueDomain");
    const simEmail = document.getElementById("simEmail");
    const simTier = document.getElementById("simTier");
    const verifyKey = document.getElementById("verifyKey");
    const verifyHw = document.getElementById("verifyHw");
    const verifyDomain = document.getElementById("verifyDomain");
    const quotaKey = document.getElementById("quotaKey");
    const quotaCredits = document.getElementById("quotaCredits");

    let cachedPublicKeyHex = null;
    let simEmailDirty = false;

    // Keep simulator inputs synchronized with issue form unless manually edited
    issueEmail.addEventListener("input", () => {
        if (!simEmailDirty) {
            simEmail.value = issueEmail.value;
        }
    });
    simEmail.addEventListener("input", () => {
        simEmailDirty = true;
    });
    issueTier.addEventListener("change", () => {
        simTier.value = issueTier.value;
    });

    // Hero CTA smooth focus into interactive generator
    const btnHeroStart = document.getElementById("btnHeroStart");
    const cardIssue = document.getElementById("cardIssue");
    btnHeroStart.addEventListener("click", () => {
        document.getElementById("console-section").scrollIntoView({ behavior: "smooth" });
        cardIssue.classList.add("pulse-focus");
        issueEmail.focus();
        setTimeout(() => cardIssue.classList.remove("pulse-focus"), 1400);
    });

    function renderBox(el, payload, state = "ok") {
        el.classList.remove("is-hidden", "is-idle", "state-ok", "state-warn", "state-err");
        // Reinicia la animación de entrada para que cada respuesta nueva sea perceptible
        el.style.animation = "none";
        void el.offsetWidth;
        el.style.animation = "";
        el.classList.add(`state-${state}`);
        el.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
    }

    function classifyResponse(res, body) {
        if (!res.ok || body.success === false) {
            return "err";
        }
        const inner = body.data || {};
        if (inner.valid === false || inner.is_valid === false) {
            return "err";
        }
        const warningHeader = res.headers.get("X-Subscription-Warning");
        if (warningHeader || inner.status === "grace_period" || inner.license_status === "grace_period") {
            return "warn";
        }
        return "ok";
    }

    // Botones que requieren un token en su campo para tener sentido
    const keyBound = [
        { input: verifyKey, ids: ["btnVerifyOnline", "btnVerifyOffline", "btnActivate", "btnRevoke"] },
        { input: quotaKey, ids: ["btnQuotaBalance", "btnQuotaDeduct", "btnQuotaReplenish"] },
    ];
    function syncKeyBoundButtons() {
        for (const { input, ids } of keyBound) {
            const empty = !input.value.trim();
            for (const id of ids) {
                const b = document.getElementById(id);
                if (b && !b.classList.contains("is-loading")) {
                    b.disabled = empty;
                    b.title = empty ? "Introduce un token" : "";
                }
            }
        }
    }
    verifyKey.addEventListener("input", syncKeyBoundButtons);
    quotaKey.addEventListener("input", syncKeyBoundButtons);

    async function withButtonLock(btn, loadingLabel, taskFn) {
        if (btn.disabled) return;
        btn.disabled = true;
        btn.classList.add("is-loading");
        btn.setAttribute("aria-busy", "true");
        btn.setAttribute("aria-label", loadingLabel);
        try {
            await taskFn();
        } finally {
            btn.classList.remove("is-loading");
            btn.removeAttribute("aria-busy");
            btn.removeAttribute("aria-label");
            btn.disabled = false;
            syncKeyBoundButtons();
        }
    }

    function propagateLicenseKey(newKey, tierLabel, seats, credits) {
        if (!newKey) return;
        verifyKey.value = newKey;
        quotaKey.value = newKey;
        const previewToken = document.getElementById("heroPreviewToken");
        const previewEnt = document.getElementById("heroPreviewEntitlements");
        const previewStatus = document.getElementById("heroPreviewStatus");
        if (previewToken) {
            previewToken.textContent = newKey.length > 36 ? `${newKey.slice(0, 24)}...${newKey.slice(-10)}` : newKey;
        }
        if (previewEnt && seats && credits !== undefined) {
            previewEnt.textContent = `${seats} nodos / ${credits} créditos (${(tierLabel || "pro").toUpperCase()})`;
        }
        if (previewStatus) {
            previewStatus.textContent = "Clave activa";
        }
        syncKeyBoundButtons();
    }

    function normalizeDomainHost(raw, allowWildcard = false) {
        if (typeof raw !== "string") return null;
        let s = raw.trim();
        if (!s || /[\/\\@?#\s]/.test(s)) return null;
        let wildcard = false;
        if (s.startsWith("*.")) {
            if (!allowWildcard) return null;
            wildcard = true;
            s = s.slice(2);
        } else if (s.includes("*")) {
            return null;
        }
        if (s.includes(":")) {
            const idx = s.lastIndexOf(":");
            const portPart = s.slice(idx + 1);
            if (!/^\d+$/.test(portPart)) return null;
            const portNum = Number(portPart);
            if (portNum < 1 || portNum > 65535) return null;
            s = s.slice(0, idx);
        }
        s = s.replace(/\.+$/, "");
        if (!s || s.startsWith(".") || s.includes("..")) return null;
        const labels = s.split(".");
        if (wildcard && labels.length < 2) return null;
        try {
            const parsed = new URL(`https://${s}`);
            const host = parsed.hostname.replace(/\.+$/, "").toLowerCase();
            if (!host) return null;
            return wildcard ? `*.${host}` : host;
        } catch {
            return null;
        }
    }

    function matchesAllowedDomains(allowedList, domainInput) {
        if (!Array.isArray(allowedList) || allowedList.length === 0) return true;
        const candidate = normalizeDomainHost(domainInput, false);
        if (!candidate) return false;
        for (const rawPattern of allowedList) {
            const pat = normalizeDomainHost(rawPattern, true);
            if (!pat) continue;
            if (pat === candidate) return true;
            if (pat.startsWith("*.")) {
                const suffix = pat.slice(2);
                if (suffix && suffix.includes(".") && (candidate === suffix || candidate.endsWith(`.${suffix}`))) {
                    return true;
                }
            }
        }
        return false;
    }

    async function refreshTelemetry(targetKey) {
        const telemetryResult = document.getElementById("telemetryResult");
        const key = (targetKey || quotaKey.value || verifyKey.value || "").trim();
        if (!key) {
            renderBox(telemetryResult, "Sin token. Emite una licencia o pega una en el panel 02.", "warn");
            return;
        }
        try {
            const res = await fetch(`/api/v1/telemetry/events?license_key=${encodeURIComponent(key)}`);
            const body = await res.json();
            renderBox(telemetryResult, body, classifyResponse(res, body));
        } catch (err) {
            renderBox(telemetryResult, { error: err.message }, "err");
        }
    }

    // Helper: base64url -> Uint8Array
    function base64UrlToBytes(b64url) {
        const pad = "=".repeat((4 - (b64url.length % 4)) % 4);
        const base64 = (b64url + pad).replace(/-/g, "+").replace(/_/g, "/");
        const raw = atob(base64);
        const out = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i += 1) {
            out[i] = raw.charCodeAt(i);
        }
        return out;
    }

    function hexToBytes(hex) {
        const clean = hex.trim();
        const out = new Uint8Array(clean.length / 2);
        for (let i = 0; i < clean.length; i += 2) {
            out[i / 2] = parseInt(clean.substring(i, i + 2), 16);
        }
        return out;
    }

    async function getPublicKeyHex() {
        if (cachedPublicKeyHex) return cachedPublicKeyHex;
        const res = await fetch("/api/v1/licenses/public-key");
        const body = await res.json();
        if (res.ok && body.data && body.data.public_key_hex) {
            cachedPublicKeyHex = body.data.public_key_hex;
        }
        return cachedPublicKeyHex;
    }

    // 1. Issue License
    const btnIssue = document.getElementById("btnIssue");
    const issueResult = document.getElementById("issueResult");
    btnIssue.addEventListener("click", () =>
        withButtonLock(btnIssue, "Emitiendo...", async () => {
            const domainVal = issueDomain.value.trim();
            const payload = {
                customer_email: issueEmail.value.trim(),
                tier: issueTier.value,
                signing_algorithm: issueAlgo.value,
            };
            if (domainVal) {
                payload.allowed_domains = [domainVal];
                verifyDomain.value = domainVal.replace(/^\*\./, "app.");
            } else {
                verifyDomain.value = "";
            }
            verifyHw.value = "";
            try {
                const res = await fetch("/api/v1/licenses/issue", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                });
                const data = await res.json();
                renderBox(issueResult, data, classifyResponse(res, data));

                if (res.ok && data.data && data.data.license_key) {
                    if (!simEmailDirty) simEmail.value = issueEmail.value.trim();
                    simTier.value = issueTier.value;
                    propagateLicenseKey(
                        data.data.license_key,
                        data.data.tier,
                        data.data.max_seats,
                        data.data.quota_credits
                    );
                    await refreshTelemetry(data.data.license_key);
                }
            } catch (err) {
                renderBox(issueResult, { error: err.message }, "err");
            }
        })
    );

    // 2A. Verify Online
    const btnVerifyOnline = document.getElementById("btnVerifyOnline");
    const verifyResult = document.getElementById("verifyResult");
    btnVerifyOnline.addEventListener("click", () =>
        withButtonLock(btnVerifyOnline, "Verificando...", async () => {
            try {
                const res = await fetch("/api/v1/licenses/verify", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        license_key: verifyKey.value.trim(),
                        hardware_id: verifyHw.value.trim() || undefined,
                        domain: verifyDomain.value.trim() || undefined,
                    }),
                });
                const data = await res.json();
                const warn = res.headers.get("X-Subscription-Warning");
                const display = warn ? { ...data, subscription_warning: warn } : data;
                renderBox(verifyResult, display, classifyResponse(res, data));
            } catch (err) {
                renderBox(verifyResult, { error: err.message }, "err");
            }
        })
    );

    // 2B. Verify Offline (Air-Gapped Browser WebCrypto Ed25519)
    const btnVerifyOffline = document.getElementById("btnVerifyOffline");
    btnVerifyOffline.addEventListener("click", () =>
        withButtonLock(btnVerifyOffline, "Validando...", async () => {
            const token = verifyKey.value.trim();
            if (!token || !token.startsWith("LIC-") || token.split(".").length !== 2) {
                renderBox(
                    verifyResult,
                    { valid: false, mode: "offline_webcrypto", error: "ERR_MALFORMED_TOKEN" },
                    "err"
                );
                return;
            }
            try {
                const pubHex = await getPublicKeyHex();
                const dashParts = token.split("-");
                if (dashParts.length < 3) {
                    throw new Error("ERR_MALFORMED_PREFIX");
                }
                const prefixTier = dashParts[1].toLowerCase();
                const bodyAndSig = dashParts.slice(2).join("-");
                const [payloadB64, sigB64] = bodyAndSig.split(".");
                const payloadBytes = base64UrlToBytes(payloadB64);
                const sigBytes = base64UrlToBytes(sigB64);
                const decoded = JSON.parse(new TextDecoder().decode(payloadBytes));

                let cryptoVerified = false;
                let engine = "WebCrypto Ed25519";
                if (sigBytes.length !== 64) {
                    renderBox(
                        verifyResult,
                        {
                            valid: false,
                            mode: "offline_webcrypto",
                            error: "ERR_ASYMMETRIC_ED25519_REQUIRED_FOR_OFFLINE",
                        },
                        "err"
                    );
                    return;
                }

                if (window.crypto && window.crypto.subtle && pubHex) {
                    const cryptoKey = await window.crypto.subtle.importKey(
                        "raw",
                        hexToBytes(pubHex),
                        { name: "Ed25519" },
                        false,
                        ["verify"]
                    );
                    cryptoVerified = await window.crypto.subtle.verify(
                        "Ed25519",
                        cryptoKey,
                        sigBytes,
                        payloadBytes
                    );
                }

                if (!cryptoVerified) {
                    renderBox(
                        verifyResult,
                        { valid: false, mode: "offline_webcrypto", engine, error: "ERR_SIGNATURE_TAMPERED" },
                        "err"
                    );
                    return;
                }

                if (String(decoded.tier || "").toLowerCase() !== prefixTier) {
                    renderBox(
                        verifyResult,
                        { valid: false, mode: "offline_webcrypto", error: "ERR_TIER_MISMATCH" },
                        "err"
                    );
                    return;
                }

                const nowSec = Math.floor(Date.now() / 1000);
                if (decoded.expires_at && nowSec > decoded.expires_at) {
                    renderBox(
                        verifyResult,
                        { valid: false, mode: "offline_webcrypto", error: "ERR_LICENSE_EXPIRED", payload: decoded },
                        "err"
                    );
                    return;
                }

                const tokenHw = typeof decoded.machine_id === "string" ? decoded.machine_id.trim().toLowerCase() : "";
                const expectedHw = verifyHw.value.trim().toLowerCase();
                if (tokenHw && (!expectedHw || tokenHw !== expectedHw)) {
                    renderBox(
                        verifyResult,
                        { valid: false, mode: "offline_webcrypto", error: "ERR_NODE_LOCK_VIOLATION" },
                        "err"
                    );
                    return;
                }

                if (
                    Array.isArray(decoded.allowed_domains) &&
                    decoded.allowed_domains.length > 0 &&
                    !matchesAllowedDomains(decoded.allowed_domains, verifyDomain.value)
                ) {
                    renderBox(
                        verifyResult,
                        { valid: false, mode: "offline_webcrypto", error: "ERR_DOMAIN_LOCK_VIOLATION" },
                        "err"
                    );
                    return;
                }

                renderBox(
                    verifyResult,
                    {
                        valid: true,
                        mode: "offline_airgapped",
                        engine,
                        payload: decoded,
                    },
                    "ok"
                );
            } catch (err) {
                renderBox(
                    verifyResult,
                    { valid: false, mode: "offline_webcrypto", error: err.message },
                    "err"
                );
            }
        })
    );

    // 2C. Activate Node
    const btnActivate = document.getElementById("btnActivate");
    btnActivate.addEventListener("click", () =>
        withButtonLock(btnActivate, "Activando...", async () => {
            const hw = verifyHw.value.trim() || "hw-console-node-01";
            verifyHw.value = hw;
            try {
                const res = await fetch("/api/v1/licenses/activate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        license_key: verifyKey.value.trim(),
                        hardware_id: hw,
                        machine_name: "Web-Console-Node",
                    }),
                });
                const data = await res.json();
                renderBox(verifyResult, data, classifyResponse(res, data));
                if (res.ok) await refreshTelemetry(verifyKey.value.trim());
            } catch (err) {
                renderBox(verifyResult, { error: err.message }, "err");
            }
        })
    );

    // 2D. Revoke License
    const btnRevoke = document.getElementById("btnRevoke");
    btnRevoke.addEventListener("click", () =>
        withButtonLock(btnRevoke, "Revocando...", async () => {
            const key = verifyKey.value.trim();
            const shortKey = key.length > 40 ? `${key.slice(0, 20)}…${key.slice(-8)}` : key;
            if (!window.confirm(`Revocar ${shortKey}\n\nLa revocación es definitiva: verificación online y cuotas dejarán de aceptarla.`)) {
                return;
            }
            try {
                const res = await fetch("/api/v1/licenses/revoke", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        license_key: verifyKey.value.trim(),
                        reason: "Revocación manual desde consola",
                    }),
                });
                const data = await res.json();
                renderBox(verifyResult, data, res.ok ? "warn" : "err");
            } catch (err) {
                renderBox(verifyResult, { error: err.message }, "err");
            }
        })
    );

    // 3A. Quota Balance
    const btnQuotaBalance = document.getElementById("btnQuotaBalance");
    const quotaResult = document.getElementById("quotaResult");
    btnQuotaBalance.addEventListener("click", () =>
        withButtonLock(btnQuotaBalance, "Consultando...", async () => {
            const key = quotaKey.value.trim();
            try {
                const res = await fetch(`/api/v1/quota/balance?license_key=${encodeURIComponent(key)}`);
                const data = await res.json();
                renderBox(quotaResult, data, classifyResponse(res, data));
            } catch (err) {
                renderBox(quotaResult, { error: err.message }, "err");
            }
        })
    );

    // 3B. Quota Deduct
    const btnQuotaDeduct = document.getElementById("btnQuotaDeduct");
    btnQuotaDeduct.addEventListener("click", () =>
        withButtonLock(btnQuotaDeduct, "Deduciendo...", async () => {
            const key = quotaKey.value.trim();
            const credits = parseInt(quotaCredits.value || "1", 10);
            try {
                const res = await fetch("/api/v1/quota/deduct", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        license_key: key,
                        credits: credits,
                        idempotency_key: "ui_" + crypto.randomUUID(),
                        event_type: "console_deduction",
                    }),
                });
                const data = await res.json();
                const warn = res.headers.get("X-Subscription-Warning");
                const display = warn ? { ...data, subscription_warning: warn } : data;
                renderBox(quotaResult, display, classifyResponse(res, data));
                if (res.ok) await refreshTelemetry(key);
            } catch (err) {
                renderBox(quotaResult, { error: err.message }, "err");
            }
        })
    );

    // 3C. Quota Replenish
    const btnQuotaReplenish = document.getElementById("btnQuotaReplenish");
    btnQuotaReplenish.addEventListener("click", () =>
        withButtonLock(btnQuotaReplenish, "Recargando...", async () => {
            const key = quotaKey.value.trim();
            const credits = parseInt(quotaCredits.value || "50", 10);
            try {
                const res = await fetch("/api/v1/quota/replenish", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        license_key: key,
                        credits: credits,
                        reset_cycle: false,
                    }),
                });
                const data = await res.json();
                renderBox(quotaResult, data, classifyResponse(res, data));
            } catch (err) {
                renderBox(quotaResult, { error: err.message }, "err");
            }
        })
    );

    // 4. Simulate Signed Webhook
    const btnSimulate = document.getElementById("btnSimulate");
    const simResult = document.getElementById("simResult");
    btnSimulate.addEventListener("click", () =>
        withButtonLock(btnSimulate, "Ejecutando...", async () => {
            const provider = document.getElementById("simProvider").value;
            const eventType = document.getElementById("simEvent").value;
            const email = simEmail.value.trim() || issueEmail.value.trim();
            const tier = simTier.value || issueTier.value;
            try {
                const res = await fetch("/api/v1/billing/simulate-webhook", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        provider: provider,
                        event_type: eventType,
                        customer_email: email,
                        tier: tier,
                    }),
                });
                const data = await res.json();
                const innerResult = (data.data && data.data.result) || {};
                const state = !res.ok
                    ? "err"
                    : eventType === "invoice.payment_failed" || eventType === "customer.subscription.deleted"
                      ? "warn"
                      : "ok";
                renderBox(simResult, data, state);

                const newKey = (data.data && data.data.license_key) || innerResult.license_key;
                if (newKey) {
                    propagateLicenseKey(newKey, tier);
                    await refreshTelemetry(newKey);
                }
            } catch (err) {
                renderBox(simResult, { error: err.message }, "err");
            }
        })
    );

    // 5. Telemetry Refresh
    const btnTelemetryRefresh = document.getElementById("btnTelemetryRefresh");
    btnTelemetryRefresh.addEventListener("click", () =>
        withButtonLock(btnTelemetryRefresh, "Cargando...", async () => {
            await refreshTelemetry();
        })
    );

    // 6. Pricing Checkout & Customer Portal
    const billingActionCard = document.getElementById("billingActionCard");
    const billingResult = document.getElementById("billingResult");

    document.querySelectorAll(".js-checkout-link").forEach((link) => {
        link.addEventListener("click", () => {
            const tier = link.getAttribute("data-tier") || "indie";
            showToast(`Abriendo Stripe Checkout (${tier.toUpperCase()})...`);
        });
    });

    document.querySelectorAll(".js-checkout-tier").forEach((btn) => {
        btn.addEventListener("click", () =>
            withButtonLock(btn, "Generando Checkout...", async () => {
                const selectedTier = btn.getAttribute("data-tier") || "pro";
                const email = issueEmail.value.trim() || "demo@empresa.com";
                try {
                    const res = await fetch("/api/v1/billing/checkout", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            customer_email: email,
                            tier: selectedTier,
                            provider: document.getElementById("simProvider").value,
                        }),
                    });
                    const data = await res.json();
                    billingActionCard.classList.remove("is-hidden");
                    renderBox(billingResult, data, classifyResponse(res, data));
                    billingActionCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
                } catch (err) {
                    billingActionCard.classList.remove("is-hidden");
                    renderBox(billingResult, { error: err.message }, "err");
                }
            })
        );
    });

    const btnBillingPortal = document.getElementById("btnBillingPortal");
    btnBillingPortal.addEventListener("click", () =>
        withButtonLock(btnBillingPortal, "Abriendo Portal...", async () => {
            const email = issueEmail.value.trim() || "demo@empresa.com";
            try {
                const res = await fetch("/api/v1/billing/portal", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ customer_email: email }),
                });
                const data = await res.json();
                renderBox(billingResult, data, classifyResponse(res, data));
            } catch (err) {
                renderBox(billingResult, { error: err.message }, "err");
            }
        })
    );

    // 7. Toast Notification System
    const toast = document.getElementById("toast");
    let toastTimeout = null;
    function showToast(message) {
        if (!toast) return;
        toast.textContent = message;
        toast.classList.remove("is-hidden");
        clearTimeout(toastTimeout);
        toastTimeout = setTimeout(() => {
            toast.classList.add("is-hidden");
        }, 2800);
    }

    // 8. Self-Service Buyer Portal Lookup
    const btnPortalLookup = document.getElementById("btnPortalLookup");
    const portalQuery = document.getElementById("portalQuery");
    const portalResults = document.getElementById("portalResults");
    const portalError = document.getElementById("portalError");
    const portalCustomerEmail = document.getElementById("portalCustomerEmail");
    const portalCustomerCount = document.getElementById("portalCustomerCount");
    const portalLicensesContainer = document.getElementById("portalLicensesContainer");
    const portalPySnippet = document.getElementById("portalPySnippet");
    const portalTsSnippet = document.getElementById("portalTsSnippet");

    if (btnPortalLookup && portalQuery) {
        btnPortalLookup.addEventListener("click", () =>
            withButtonLock(btnPortalLookup, "Consultando...", async () => {
                const q = portalQuery.value.trim();
                if (!q) {
                    showToast("Por favor introduce un email o token de licencia.");
                    return;
                }
                portalResults.classList.add("is-hidden");
                portalError.classList.add("is-hidden");

                try {
                    const res = await fetch("/api/v1/billing/portal/lookup", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ query: q }),
                    });
                    const json = await res.json();
                    if (!res.ok || !json.success) {
                        portalError.textContent = json.detail || json.error || "No se encontraron licencias para la consulta introducida.";
                        portalError.classList.remove("is-hidden");
                        return;
                    }
                    const data = json.data;
                    portalCustomerEmail.textContent = `Licencias de ${data.customer_email}`;
                    portalCustomerCount.textContent = `${data.total_licenses} licencia(s) · Clave pública Ed25519: ${data.public_key_hex.slice(0, 16)}...`;

                    portalLicensesContainer.innerHTML = data.licenses.map(lic => `
                        <div style="background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 14px; margin-bottom: 12px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                                <strong style="color: var(--ink);">${lic.tier.toUpperCase()}</strong>
                                <span class="tag ${lic.status === 'active' ? '' : 'tag-warn'}">${lic.status}</span>
                            </div>
                            <div style="font-family: var(--mono); font-size: 11px; word-break: break-all; background: var(--sunken); padding: 8px; border-radius: 4px; margin-bottom: 8px; color: var(--ink);">${lic.license_key}</div>
                            <div style="display: flex; gap: 16px; font-size: 13px; color: var(--muted); flex-wrap: wrap;">
                                <span>Saldo créditos: <b style="color: var(--ink);">${Number(lic.credit_balance).toLocaleString()}</b></span>
                                <span>Nodos activos: <b style="color: var(--ink);">${lic.current_activations} / ${lic.max_seats}</b></span>
                                <span>Caducidad: <b style="color: var(--ink);">${lic.expires_at ? lic.expires_at.split('T')[0] : 'Permanente'}</b></span>
                            </div>
                        </div>
                    `).join("");

                    portalPySnippet.textContent = data.python_snippet;
                    portalTsSnippet.textContent = data.typescript_snippet;
                    portalResults.classList.remove("is-hidden");
                } catch (err) {
                    portalError.textContent = `Consulta no disponible en modo estático sin backend. Requiere gateway KeyFlint activo en Railway/Render: ${err.message}`;
                    portalError.classList.remove("is-hidden");
                }
            })
        );
    }

    // 8. Interactive Code Showcase Tabs
    const codeSnippet = document.getElementById("codeSnippet");
    const btnCopySnippet = document.getElementById("btnCopySnippet");
    const codeSnippets = {
        "python-mcp": `<span class="hl-kw">from</span> keyflint_verify.mcp <span class="hl-kw">import</span> KeyFlint

kf = KeyFlint()  <span class="hl-cm"># lee KEYFLINT_LICENSE, KEYFLINT_PUBLIC_KEYS y KEYFLINT_URL</span>

<span class="hl-cm"># 2 créditos por llamada; reembolso automático si la tool lanza o devuelve isError</span>
<span class="hl-fn">@mcp.tool</span>()
<span class="hl-fn">@kf.metered</span>(credits=2)
<span class="hl-kw">async def</span> <span class="hl-fn">analizar_codigo</span>(repo_url: str) -> str:
    <span class="hl-kw">return await</span> run_ai_audit(repo_url)`,

        "ts-mcp": `<span class="hl-kw">import</span> { createKeyFlint } <span class="hl-kw">from</span> <span class="hl-str">"keyflint-verify/mcp"</span>;

<span class="hl-kw">const</span> kf = createKeyFlint({ gatewayUrl: <span class="hl-str">"https://licenses.tu-dominio.com"</span> });

<span class="hl-cm">// Descuento atómico por llamada en @modelcontextprotocol/sdk</span>
server.tool(<span class="hl-str">"analizar_codigo"</span>, schema, kf.metered(2, <span class="hl-kw">async</span> (args) => {
    <span class="hl-kw">return await</span> runAiAudit(args);
}));`,

        "python-offline": `<span class="hl-kw">from</span> keyflint_verify <span class="hl-kw">import</span> validate_offline

<span class="hl-cm"># Verificación local, sin red</span>
is_valid, payload, err = validate_offline(
    license_token=<span class="hl-str">"LIC-PRO-eyJ..."</span>,
    public_key_hex=<span class="hl-str">"0043b567..."</span>,
    expected_machine_id=<span class="hl-str">"nodo-prod-01"</span>
)
<span class="hl-kw">if not</span> is_valid:
    sys.exit(<span class="hl-str">f"Licencia inválida: {err}"</span>)`,

        "js-webcrypto": `<span class="hl-kw">import</span> { verifyLicense } <span class="hl-kw">from</span> <span class="hl-str">"keyflint-verify"</span>;

<span class="hl-cm">// Web Crypto: mismo código en Node y navegador</span>
<span class="hl-kw">const</span> { valid, payload, error } = <span class="hl-kw">await</span> verifyLicense(token, publicKeyHex);
<span class="hl-kw">if</span> (!valid) {
    <span class="hl-kw">throw new</span> Error(<span class="hl-str">\`Acceso denegado: \${error}\`</span>);
}`,

        "go-offline": `<span class="hl-kw">import</span> keyflint <span class="hl-str">"github.com/ArceeDev/keyflint/sdks/go-verify"</span>

<span class="hl-cm">// go get github.com/ArceeDev/keyflint/sdks/go-verify@v1.2.0 · sin red, sin dependencias</span>
payload, err := keyflint.Verify(os.Getenv(<span class="hl-str">"KEYFLINT_LICENSE"</span>), publicKeyHex)
<span class="hl-kw">if</span> err != <span class="hl-kw">nil</span> {
    log.Fatalf(<span class="hl-str">"licencia inválida: %s"</span>, keyflint.Code(err))
}
fmt.Println(payload.Tier, payload.Features)`
    };

    document.querySelectorAll(".tab-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach((b) => {
                b.classList.remove("active");
                b.setAttribute("aria-selected", "false");
            });
            btn.classList.add("active");
            btn.setAttribute("aria-selected", "true");
            const tabKey = btn.getAttribute("data-tab");
            if (codeSnippet && codeSnippets[tabKey]) {
                codeSnippet.innerHTML = codeSnippets[tabKey];
            }
        });
    });

    if (btnCopySnippet) {
        btnCopySnippet.addEventListener("click", async () => {
            const rawText = codeSnippet.textContent || codeSnippet.innerText;
            try {
                await navigator.clipboard.writeText(rawText);
                showToast("Copiado");
                btnCopySnippet.textContent = "Copiado";
                setTimeout(() => (btnCopySnippet.textContent = "Copiar"), 1400);
            } catch (err) {
                showToast("Selecciona el código para copiar");
            }
        });
    }

    // 8b. Copy & paste generator (language, credits, public key)
    const genLang = document.getElementById("genLang");
    const genCredits = document.getElementById("genCredits");
    const genPubKey = document.getElementById("genPubKey");
    const genGateway = document.getElementById("genGateway");
    const genOutput = document.getElementById("genOutput");
    const btnCopyGenerated = document.getElementById("btnCopyGenerated");

    function buildSnippet(lang, credits, pub, gateway) {
        const key = /^[0-9a-fA-F]{64}$/.test(pub) ? pub.toLowerCase() : "PEGA_AQUI_TU_CLAVE_PUBLICA_HEX";
        const gw = gateway || "https://licencias.tu-dominio.com";
        const n = Number.isInteger(credits) && credits > 0 ? credits : 0;
        if (lang === "ts") {
            const wrap = n ? `kf.metered(${n}, async ({ query }: { query: string }) => {` : "kf.requireLicense(async ({ query }: { query: string }) => {";
            return [
                "// npm i keyflint-verify @modelcontextprotocol/sdk zod",
                'import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";',
                'import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";',
                'import { z } from "zod";',
                'import { createKeyFlint } from "keyflint-verify/mcp";',
                "",
                `const kf = createKeyFlint({ publicKeys: ${JSON.stringify(key)}${n ? `, gatewayUrl: ${JSON.stringify(gw)}` : ""} });`,
                'const server = new McpServer({ name: "mi-herramienta", version: "1.0.0" });',
                "",
                n ? `// ${n} crédito(s) por llamada; se devuelven si la tool falla` : "// Solo licencia (offline, sin red)",
                'server.registerTool("buscar", { inputSchema: { query: z.string() } }, ' + wrap,
                '  return { content: [{ type: "text" as const, text: `Resultado para ${query}` }] };',
                "}));",
                "",
                "await server.connect(new StdioServerTransport());",
            ].join("\n");
        }
        if (lang === "go") {
            return [
                "// go get github.com/ArceeDev/keyflint/sdks/go-verify@v1.2.0",
                "package main",
                "",
                "import (",
                '\t"fmt"',
                '\t"log"',
                '\t"os"',
                "",
                '\tkeyflint "github.com/ArceeDev/keyflint/sdks/go-verify"',
                ")",
                "",
                `const publicKeyHex = ${JSON.stringify(key)}`,
                "",
                "func main() {",
                '\tpayload, err := keyflint.Verify(os.Getenv("KEYFLINT_LICENSE"), publicKeyHex)',
                "\tif err != nil {",
                '\t\tlog.Fatalf("licencia inválida: %s", keyflint.Code(err))',
                "\t}",
                '\tfmt.Println("licencia OK:", payload.Tier)',
                n ? `\t// Para cobrar ${n} crédito(s) por llamada: POST ${gw}/api/v1/quota/deduct` : null,
                "}",
            ].filter((l) => l !== null).join("\n");
        }
        return [
            "# pip install keyflint-verify mcp",
            "from mcp.server.fastmcp import FastMCP",
            "from keyflint_verify.mcp import KeyFlint",
            "",
            `kf = KeyFlint(public_keys=${JSON.stringify(key)}${n ? `, gateway_url=${JSON.stringify(gw)}` : ""})`,
            'mcp = FastMCP("mi-herramienta")',
            "",
            n ? `# ${n} crédito(s) por llamada; se devuelven si la tool falla` : "# Solo licencia (offline, sin red)",
            "@mcp.tool()",
            n ? `@kf.metered(credits=${n})` : "@kf.require_license",
            "def buscar(query: str) -> str:",
            '    return f"Resultado para {query}"',
            "",
            'if __name__ == "__main__":',
            "    mcp.run()",
        ].join("\n");
    }

    function renderGenerated() {
        if (!genOutput) return;
        genOutput.textContent = buildSnippet(
            genLang.value,
            parseInt(genCredits.value, 10),
            genPubKey.value.trim(),
            genGateway.value.trim()
        );
    }

    if (genOutput) {
        [genLang, genCredits, genPubKey, genGateway].forEach((el) => el.addEventListener("input", renderGenerated));
        genLang.addEventListener("change", renderGenerated);
        renderGenerated();
        btnCopyGenerated.addEventListener("click", async () => {
            try {
                await navigator.clipboard.writeText(genOutput.textContent);
                showToast("Código copiado");
            } catch (err) {
                showToast("Selecciona el código para copiar");
            }
        });
    }

    // 8c. Self-service node release
    const nodesKey = document.getElementById("nodesKey");
    const btnNodesList = document.getElementById("btnNodesList");
    const nodesList = document.getElementById("nodesList");
    const nodesResult = document.getElementById("nodesResult");

    async function postJson(url, body) {
        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        const data = await res.json().catch(() => ({}));
        return { res, data };
    }

    function showNodesError(res, data) {
        nodesResult.classList.remove("is-hidden");
        renderBox(nodesResult, data, classifyResponse(res, data));
    }

    async function loadNodes() {
        const key = nodesKey.value.trim();
        if (!key) return;
        nodesList.textContent = "";
        nodesResult.classList.add("is-hidden");
        try {
            const { res, data } = await postJson("/api/v1/licenses/nodes", { license_key: key });
            if (!res.ok) return showNodesError(res, data);
            const info = data.data || {};
            const head = document.createElement("p");
            head.className = "card-sub";
            head.textContent = `${info.current_activations || 0} de ${info.max_seats || 0} asientos en uso`;
            nodesList.appendChild(head);
            (info.nodes || []).forEach((node) => {
                const row = document.createElement("div");
                row.className = "form-row";
                const label = document.createElement("code");
                label.textContent = `${node.machine_name || "equipo"} · ${node.hardware_id}`;
                label.style.flex = "3";
                label.style.overflowWrap = "anywhere";
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "btn btn-secondary btn-inline";
                btn.textContent = "Liberar";
                btn.addEventListener("click", () =>
                    withButtonLock(btn, "Liberando...", async () => {
                        const r = await postJson("/api/v1/licenses/nodes/release", {
                            license_key: key,
                            hardware_id: node.hardware_id,
                        });
                        if (!r.res.ok) return showNodesError(r.res, r.data);
                        showToast("Nodo liberado");
                        await loadNodes();
                    })
                );
                row.append(label, btn);
                nodesList.appendChild(row);
            });
        } catch (err) {
            nodesResult.classList.remove("is-hidden");
            renderBox(nodesResult, { error: `Requiere un gateway KeyFlint activo: ${err.message}` }, "err");
        }
    }

    if (btnNodesList) {
        btnNodesList.addEventListener("click", () => withButtonLock(btnNodesList, "Cargando...", loadNodes));
    }

    // 9. Hero Token Copy Interaction
    const heroPreviewToken = document.getElementById("heroPreviewToken");
    if (heroPreviewToken) {
        heroPreviewToken.style.cursor = "pointer";
        heroPreviewToken.title = "Haz clic para copiar el token";
        heroPreviewToken.addEventListener("click", async () => {
            const val = verifyKey.value.trim() || heroPreviewToken.textContent.trim();
            if (val && !val.includes("<")) {
                try {
                    await navigator.clipboard.writeText(val);
                    showToast("Token copiado");
                } catch {
                    showToast("Error al copiar");
                }
            }
        });
    }

    // 10. FAQ Accordion Interaction
    document.querySelectorAll(".faq-question").forEach((q) => {
        q.addEventListener("click", () => {
            const parent = q.parentElement;
            const isOpen = parent.classList.contains("open");
            document.querySelectorAll(".faq-item").forEach((item) => {
                item.classList.remove("open");
                const b = item.querySelector(".faq-question");
                if (b) b.setAttribute("aria-expanded", "false");
            });
            if (!isOpen) {
                parent.classList.add("open");
                q.setAttribute("aria-expanded", "true");
            }
        });
    });

    // 11. Enter en un campo ejecuta la acción principal de su panel
    const enterMap = [
        [["issueEmail", "issueDomain"], "btnIssue"],
        [["verifyKey", "verifyHw", "verifyDomain"], "btnVerifyOnline"],
        [["quotaKey", "quotaCredits"], "btnQuotaDeduct"],
        [["simEmail"], "btnSimulate"],
    ];
    for (const [inputIds, btnId] of enterMap) {
        for (const id of inputIds) {
            const el = document.getElementById(id);
            if (!el) continue;
            el.addEventListener("keydown", (e) => {
                if (e.key === "Enter" && !e.isComposing) {
                    e.preventDefault();
                    document.getElementById(btnId).click();
                }
            });
        }
    }

    syncKeyBoundButtons();
});
