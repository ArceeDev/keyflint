"""Tier 2: Boundary & Corner Cases — Checkout, Input Sanitization & SQL Injection Defense.

Covers:
46. test_bound5_checkout_invalid_tier_returns_422
47. test_bound5_checkout_empty_customer_email_rejected
48. test_bound5_sql_injection_in_metadata_neutralized
49. test_bound5_oversized_payload_exceeding_max_bytes_rejected
50. test_bound5_unicode_special_chars_in_customer_name_preserved
"""

from __future__ import annotations

import unittest
from tests.conftest import BaseKeyForgeTestCase


class TestCheckoutBoundaries(BaseKeyForgeTestCase):
    """Boundary verification for input validation, sanitization, and security thresholds."""

    def test_bound5_checkout_invalid_tier_returns_422(self):
        """Requesting tier 'diamond' rejected with 422 Unprocessable Entity."""
        self.require_app()
        res = self.client.post("/api/v1/billing/checkout", json={
            "customer_email": "alex@acme.ai",
            "tier": "diamond_unlimited"
        })
        self.assertEqual(res.status_code, 422, f"Invalid tier should yield 422: {res.text}")

    def test_bound5_checkout_empty_customer_email_rejected(self):
        """Missing or empty email is rejected with 422."""
        self.require_app()
        res = self.client.post("/api/v1/billing/checkout", json={
            "customer_email": "",
            "tier": "pro"
        })
        self.assertEqual(res.status_code, 422)

    def test_bound5_sql_injection_in_metadata_neutralized(self):
        """Metadata containing SQL injection attacks stored safely via parameters without SQL execution."""
        self.require_app()
        injection_str = "'; DROP TABLE quotas; DROP TABLE licenses; --"
        data = self.issue_license_api(customer_email="sql_defense@acme.ai", tier="community")
        license_key = data["license_key"]

        # Deduct with SQL injection string in metadata
        res = self.deduct_quota_api(
            license_key=license_key,
            credits=1,
            event_type="test_sql_defense",
            metadata={"notes": injection_str, "role": "admin' OR '1'='1"}
        )
        self.assertEqual(res.status_code, 200, "Sanitized input should succeed without SQL error")

        # Verify quotas table was NOT dropped
        bal_res = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
        self.assertEqual(bal_res.status_code, 200, "Quotas table must remain intact after injection payload")

    def test_bound5_oversized_payload_exceeding_max_bytes_rejected(self):
        """Payloads > 64KB rejected with HTTP 413 PAYLOAD_TOO_LARGE (both Content-Length and chunked/streamed)."""
        self.require_app()
        huge_blob = "A" * (70 * 1024)  # 70KB
        res = self.client.post("/api/v1/licenses/issue", json={
            "customer_email": "huge@acme.ai",
            "tier": "pro",
            "metadata": {"blob": huge_blob}
        })
        self.assertEqual(res.status_code, 413, f"Oversized payload must return 413: {res.text}")
        self.assertEqual(res.json().get("error", {}).get("code"), "PAYLOAD_TOO_LARGE")

        # Malformed Content-Length header returns 400 INVALID_CONTENT_LENGTH
        bad_cl = self.client.post(
            "/api/v1/licenses/issue",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "not-a-number"},
        )
        self.assertEqual(bad_cl.status_code, 400)
        self.assertEqual(bad_cl.json().get("error", {}).get("code"), "INVALID_CONTENT_LENGTH")

        # Streamed generator exceeding 64KB without Content-Length returns 413
        def oversized_stream():
            for _ in range(70):
                yield b"B" * 1024

        stream_res = self.client.post(
            "/api/v1/licenses/issue",
            content=oversized_stream(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(stream_res.status_code, 413)
        self.assertEqual(stream_res.json().get("error", {}).get("code"), "PAYLOAD_TOO_LARGE")

    def test_bound5_unicode_special_chars_in_customer_name_preserved(self):
        """Supports international characters safely without encoding corruption."""
        self.require_app()
        unicode_email = "münchen.schäfer+test@über-tech.de"
        data = self.issue_license_api(customer_email=unicode_email, tier="pro")
        self.assertIn("license_key", data)

        res = self.verify_license_api(license_key=data["license_key"])
        self.assertEqual(res.status_code, 200)

    def test_bound5_security_headers_and_request_id_sync(self):
        """Security headers are present on 200 and 4xx responses, and X-Request-ID matches metadata.request_id."""
        self.require_app()
        custom_req_id = "req-audit-trace-001"
        res_ok = self.client.get("/api/v1/health", headers={"X-Request-ID": custom_req_id})
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.headers.get("X-Request-ID"), custom_req_id)
        self.assertEqual(res_ok.json().get("metadata", {}).get("request_id"), custom_req_id)

        for hdr in (
            "content-security-policy",
            "strict-transport-security",
            "referrer-policy",
            "x-content-type-options",
            "x-frame-options",
        ):
            self.assertIn(hdr, {k.lower() for k in res_ok.headers.keys()}, f"Missing security header: {hdr}")

        # Error envelope must also carry synced auto-generated request_id and security headers
        res_err = self.client.post("/api/v1/billing/checkout", json={"customer_email": "", "tier": "pro"})
        self.assertEqual(res_err.status_code, 422)
        header_req_id = res_err.headers.get("X-Request-ID")
        self.assertTrue(header_req_id)
        self.assertEqual(res_err.json().get("metadata", {}).get("request_id"), header_req_id)
        self.assertEqual(res_err.headers.get("X-Frame-Options"), "DENY")

    def test_bound5_production_secret_and_admin_guards(self):
        """Production mode rejects default secrets at startup and enforces X-Admin-Key + disables simulate-webhook."""
        import os
        from app.config import Settings, get_settings

        # 1. Default secrets fail fast in production
        with self.assertRaises(RuntimeError):
            Settings(ENVIRONMENT="production").validate_production_secrets()

        # 2. Strong unique secrets pass production validation
        strong_priv = "b1" * 32
        strong_settings = Settings(
            ENVIRONMENT="production",
            SECRET_KEY="prod_hmac_secret_key_with_high_entropy_9876543210",
            ED25519_PRIVATE_KEY_HEX=strong_priv,
            ED25519_PUBLIC_KEY_HEX="",  # derived from the private key
            STRIPE_WEBHOOK_SECRET="whsec_live_unique_stripe_secret_999999",
            LEMONSQUEEZY_WEBHOOK_SECRET="whsec_live_unique_ls_secret_999999",
            ADMIN_API_KEY="kf_live_admin_secret_key_987654321",
        )
        strong_settings.validate_production_secrets()

        # 3. Verify HTTP admin & simulation guards under ENVIRONMENT=production
        data = self.issue_license_api(customer_email="prod_guard@acme.ai", tier="pro")
        lic_key = data["license_key"]

        saved_env = {
            k: os.environ.get(k)
            for k in (
                "ENVIRONMENT",
                "ADMIN_API_KEY",
                "SECRET_KEY",
                "ED25519_PRIVATE_KEY_HEX",
                "STRIPE_WEBHOOK_SECRET",
                "LEMONSQUEEZY_WEBHOOK_SECRET",
            )
        }
        try:
            os.environ["ENVIRONMENT"] = "production"
            os.environ["ADMIN_API_KEY"] = "kf_live_admin_secret_key_987654321"
            os.environ["SECRET_KEY"] = "prod_hmac_secret_key_with_high_entropy_9876543210"
            os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_live_unique_stripe_secret_999999"
            os.environ["LEMONSQUEEZY_WEBHOOK_SECRET"] = "whsec_live_unique_ls_secret_999999"
            get_settings.cache_clear()

            # Admin endpoints reject missing/wrong X-Admin-Key with 401
            unauth_issue = self.client.post(
                "/api/v1/licenses/issue",
                json={"customer_email": "unauth@acme.ai", "tier": "pro"},
            )
            self.assertEqual(unauth_issue.status_code, 401)

            unauth_replenish = self.client.post(
                "/api/v1/quota/replenish",
                json={"license_key": lic_key, "credits": 50, "reset_cycle": False},
            )
            self.assertEqual(unauth_replenish.status_code, 401)

            unauth_revoke = self.client.post(
                "/api/v1/licenses/revoke",
                json={"license_key": lic_key, "reason": "unauthorized_attempt"},
            )
            self.assertEqual(unauth_revoke.status_code, 401)

            # Authorized admin call succeeds
            auth_replenish = self.client.post(
                "/api/v1/quota/replenish",
                json={"license_key": lic_key, "credits": 50, "reset_cycle": False},
                headers={"X-Admin-Key": "kf_live_admin_secret_key_987654321"},
            )
            self.assertEqual(auth_replenish.status_code, 200)

            # Webhook simulator is disabled (403) in production
            sim_prod = self.client.post(
                "/api/v1/billing/simulate-webhook",
                json={
                    "event_type": "invoice.payment_succeeded",
                    "customer_email": "prod_guard@acme.ai",
                    "tier": "pro",
                },
            )
            self.assertEqual(sim_prod.status_code, 403)
        finally:
            for k, val in saved_env.items():
                if val is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = val
            get_settings.cache_clear()

    def test_checkout_providers_mock_session_routes_live_mode_and_smuggling_guards(self):
        """Verifies checkout provider validation, 200 OK mock session routes, BILLING_MODE=live handling, conflicting Content-Length 400, and bounded rate limiter."""
        import os
        from app.config import get_settings
        from app.presentation.middlewares import SlidingWindowRateLimiter

        self.require_app()

        # 1. Invalid provider returns 422; valid lemonsqueezy mock checkout + portal resolve with 200 OK
        bad_prov = self.client.post(
            "/api/v1/billing/checkout",
            json={"customer_email": "prov@acme.ai", "tier": "pro", "provider": "paypal"},
        )
        self.assertEqual(bad_prov.status_code, 422)

        ls_co = self.client.post(
            "/api/v1/billing/checkout",
            json={"customer_email": "prov@acme.ai", "tier": "studio", "provider": "lemonsqueezy"},
        )
        self.assertEqual(ls_co.status_code, 200)
        co_data = ls_co.json()["data"]
        self.assertEqual(co_data["provider"], "lemonsqueezy")
        self.assertEqual(co_data["mode"], "mock")

        co_get = self.client.get(co_data["checkout_url"])
        self.assertEqual(co_get.status_code, 200)
        self.assertEqual(co_get.json()["data"]["status"], "open")

        portal_post = self.client.post("/api/v1/billing/portal", json={"customer_email": "prov@acme.ai"})
        self.assertEqual(portal_post.status_code, 200)
        portal_get = self.client.get(portal_post.json()["data"]["portal_url"])
        self.assertEqual(portal_get.status_code, 200)

        # 2. BILLING_MODE=live fails closed with 503 when unconfigured, and builds live LS URL when configured
        prev_mode = os.environ.get("BILLING_MODE")
        prev_ls_url = os.environ.get("LEMONSQUEEZY_CHECKOUT_URL")
        try:
            os.environ["BILLING_MODE"] = "live"
            os.environ.pop("LEMONSQUEEZY_CHECKOUT_URL", None)
            get_settings.cache_clear()

            unconf = self.client.post(
                "/api/v1/billing/checkout",
                json={"customer_email": "live@acme.ai", "tier": "pro", "provider": "stripe"},
            )
            self.assertEqual(unconf.status_code, 503)
            self.assertEqual(unconf.json()["error"]["code"], "BILLING_PROVIDER_UNCONFIGURED")

            os.environ["LEMONSQUEEZY_CHECKOUT_URL"] = "https://acme.lemonsqueezy.com/checkout/buy/var_123"
            get_settings.cache_clear()
            live_ls = self.client.post(
                "/api/v1/billing/checkout",
                json={"customer_email": "live@acme.ai", "tier": "pro", "provider": "lemonsqueezy"},
            )
            self.assertEqual(live_ls.status_code, 200)
            self.assertTrue(
                live_ls.json()["data"]["checkout_url"].startswith(
                    "https://acme.lemonsqueezy.com/checkout/buy/var_123?"
                )
            )
        finally:
            if prev_mode is None:
                os.environ.pop("BILLING_MODE", None)
            else:
                os.environ["BILLING_MODE"] = prev_mode
            if prev_ls_url is None:
                os.environ.pop("LEMONSQUEEZY_CHECKOUT_URL", None)
            else:
                os.environ["LEMONSQUEEZY_CHECKOUT_URL"] = prev_ls_url
            get_settings.cache_clear()

        # 3. Comma-separated conflicting Content-Length header returns 400 INVALID_CONTENT_LENGTH
        smuggle_res = self.client.post(
            "/api/v1/billing/checkout",
            content=b"{}",
            headers={"Content-Type": "application/json", "Content-Length": "2, 999999"},
        )
        self.assertEqual(smuggle_res.status_code, 400)
        self.assertEqual(smuggle_res.json()["error"]["code"], "INVALID_CONTENT_LENGTH")

        # 4. SlidingWindowRateLimiter enforces max_buckets cap
        bounded = SlidingWindowRateLimiter(max_buckets=128)
        for i in range(400):
            bounded.check(f"api:198.51.100.{i}", limit=10, window_seconds=60.0)
        self.assertLessEqual(len(bounded._buckets), 128)


if __name__ == "__main__":
    unittest.main()
