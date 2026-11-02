"""Tier 2: Boundary & Corner Cases — Quota Overdraft, Paywalls & Rate Limits.

Covers:
36. test_bound3_exact_zero_balance_triggers_paywall_402
37. test_bound3_partial_credit_insufficient_triggers_402
38. test_bound3_credit_balance_never_drops_below_zero
39. test_bound3_negative_cost_deduction_rejected
40. test_bound3_rate_limit_burst_exact_boundary_blocked_429
"""

from __future__ import annotations

import unittest
from tests.conftest import BaseKeyFlintTestCase


class TestQuotaBoundaries(BaseKeyFlintTestCase):
    """Boundary verification for quota exhaustion, paywall 402, and rate limits."""

    def test_bound3_exact_zero_balance_triggers_paywall_402(self):
        """Balance of 0 returns HTTP 402 with upgrade prompt."""
        self.require_app()
        # Community has 25 credits. Consume all 25.
        data = self.issue_license_api(customer_email="zero_bal@acme.ai", tier="community")
        license_key = data["license_key"]

        # Deduct all 25 credits
        res1 = self.deduct_quota_api(license_key=license_key, credits=25)
        self.assertEqual(res1.status_code, 200)

        # Attempt to deduct 1 more credit from 0 balance
        res2 = self.deduct_quota_api(license_key=license_key, credits=1)
        self.assertEqual(res2.status_code, 402, f"Expected 402 Payment Required: {res2.text}")
        
        body = res2.json()
        error = body.get("error", body)
        self.assertIn("QUOTA", str(error))

    def test_bound3_partial_credit_insufficient_triggers_402(self):
        """Balance of 3 attempting 5-credit action returns HTTP 402."""
        self.require_app()
        data = self.issue_license_api(customer_email="partial@acme.ai", tier="community")
        license_key = data["license_key"]

        # Reduce balance to 3 (25 - 22 = 3)
        self.deduct_quota_api(license_key=license_key, credits=22)

        # Try to deduct 5 credits
        res = self.deduct_quota_api(license_key=license_key, credits=5)
        self.assertEqual(res.status_code, 402, f"Partial insufficient credits must return 402: {res.text}")

        # Check that balance remains 3 (not decremented)
        bal_res = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
        bal_payload = bal_res.json().get("data", bal_res.json())
        self.assertEqual(bal_payload.get("credit_balance"), 3, "Balance must remain unchanged after rejected debit")

    def test_bound3_credit_balance_never_drops_below_zero(self):
        """Credit balance cannot be driven negative under any condition."""
        self.require_app()
        data = self.issue_license_api(customer_email="non_negative@acme.ai", tier="community")
        license_key = data["license_key"]

        # Attempt absurdly large deduction (999,999 credits)
        res = self.deduct_quota_api(license_key=license_key, credits=999999)
        self.assertEqual(res.status_code, 402)

        # Verify balance remains positive (25)
        bal_res = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
        bal_payload = bal_res.json().get("data", bal_res.json())
        self.assertGreaterEqual(bal_payload.get("credit_balance"), 0, "Balance must never drop below 0")

    def test_bound3_negative_cost_deduction_rejected(self):
        """Attempting deduction of zero or negative credits (0, -10) returns HTTP 422."""
        self.require_app()
        data = self.issue_license_api(customer_email="negative_cost@acme.ai", tier="community")
        license_key = data["license_key"]

        res_neg = self.deduct_quota_api(license_key=license_key, credits=-10)
        self.assertEqual(res_neg.status_code, 422, f"Negative deduction must be rejected: {res_neg.text}")

        res_zero = self.deduct_quota_api(license_key=license_key, credits=0)
        self.assertEqual(res_zero.status_code, 422, f"Zero deduction must be rejected: {res_zero.text}")

    def test_bound3_rate_limit_burst_exact_boundary_blocked_429(self):
        """Bursting requests past 25-request sliding window yields deterministic HTTP 429 + Retry-After."""
        self.require_app()
        # Request #1 in the 25-request window:
        data = self.issue_license_api(customer_email="ratelimit@acme.ai", tier="community")
        license_key = data["license_key"]

        # Requests #2..#25 (24 balance calls) must succeed (200 OK); #26..#31 (6 calls) must return 429
        statuses = []
        last_429 = None
        for _ in range(30):
            res = self.client.get(f"/api/v1/quota/balance?license_key={license_key}")
            statuses.append(res.status_code)
            if res.status_code == 429:
                last_429 = res

        self.assertEqual(statuses[:24], [200] * 24, f"First 24 calls after issue must return 200: {statuses}")
        self.assertEqual(statuses[24:], [429] * 6, f"Calls exceeding 25-req window must return 429: {statuses}")
        self.assertIsNotNone(last_429)
        self.assertIn("retry-after", {k.lower() for k in last_429.headers.keys()})
        err_body = last_429.json()
        self.assertFalse(err_body.get("success", True))
        self.assertEqual(err_body.get("error", {}).get("code"), "RATE_LIMIT_EXCEEDED")

        # Spoofing X-Forwarded-For must NOT bypass rate limiter when TRUST_PROXY_HEADERS=False
        spoof_res = self.client.get(
            f"/api/v1/quota/balance?license_key={license_key}",
            headers={"X-Forwarded-For": "203.0.113.99"},
        )
        self.assertEqual(spoof_res.status_code, 429, "Spoofed X-Forwarded-For must not bypass rate limit")

    def test_trusted_proxy_ip_cannot_be_spoofed_by_client(self):
        """Behind Fly, only Fly-Client-IP or the proxy-appended right-most X-Forwarded-For hop count."""
        from app.presentation.middlewares import RateLimitMiddleware

        extract = RateLimitMiddleware._extract_client_ip
        scope = {"client": ("10.0.0.1", 1234), "headers": [
            (b"x-forwarded-for", b"203.0.113.99, 198.51.100.7"),
            (b"fly-client-ip", b"198.51.100.7"),
        ]}
        self.assertEqual(extract(scope, trust_proxy_headers=True), "198.51.100.7")
        scope["headers"] = [(b"x-forwarded-for", b"203.0.113.99, 198.51.100.7")]
        self.assertEqual(extract(scope, trust_proxy_headers=True), "198.51.100.7")
        scope["headers"] = [(b"X-Forwarded-For", b"  ")]
        self.assertEqual(extract(scope, trust_proxy_headers=True), "10.0.0.1")
        scope["headers"] = [(b"fly-client-ip", b"198.51.100.7")]
        self.assertEqual(extract(scope, trust_proxy_headers=False), "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
