// KeyForge v1.0.0 — Interactive Admin & Cryptographic Console

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
        el.classList.remove("is-hidden", "state-ok", "state-warn", "state-err");
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

    async function withButtonLock(btn, loadingLabel, taskFn) {
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = loadingLabel;
        try {
            await taskFn();
        } finally {
            btn.disabled = false;
            btn.textContent = originalText;
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
            previewEnt.textContent = `${seats} nodos / ${credits} creditos (${(tierLabel || "pro").toUpperCase()})`;
        }
        if (previewStatus) {
            previewStatus.textContent = "CLAVE ACTIVA";
        }
    }

    async function refreshTelemetry(targetKey) {
        const telemetryResult = document.getElementById("telemetryResult");
        const key = (targetKey || quotaKey.value || verifyKey.value || "").trim();
        if (!key) {
            renderBox(telemetryResult, "Introduce o emite una clave de licencia antes de consultar la auditoria.", "warn");
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
            }
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

                const expectedHw = verifyHw.value.trim().toLowerCase();
                if (decoded.machine_id && expectedHw && decoded.machine_id.toLowerCase() !== expectedHw) {
                    renderBox(
                        verifyResult,
                        { valid: false, mode: "offline_webcrypto", error: "ERR_NODE_LOCK_MISMATCH" },
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
            try {
                const res = await fetch("/api/v1/licenses/revoke", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        license_key: verifyKey.value.trim(),
                        reason: "Revocacion manual desde consola operativa",
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
});
