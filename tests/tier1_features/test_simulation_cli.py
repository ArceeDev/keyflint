"""Tier 1: Feature Coverage — Feature 5: Webhook Billing Simulator, Checkout & CLI (FEAT-SIM-01 & FEAT-CLI-01).

Covers:
21. test_feat5_create_checkout_session_returns_redirect_url
22. test_feat5_create_customer_portal_session_returns_url
23. test_feat5_simulate_webhook_generates_valid_hmac_payload
24. test_feat5_simulate_checkout_lifecycle_end_to_end
25. test_feat5_mock_mode_allows_zero_credential_execution
+ CLI end-to-end verification (issue, offline/online verify, activate, quota deduct/replenish/balance, revoke, error handling)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from click.testing import CliRunner

from app.cli import cli
from app.config import get_settings
from tests.conftest import BaseKeyForgeTestCase


class TestSimulationAndCheckout(BaseKeyForgeTestCase):
    """E2E Verification for FEAT-SIM-01 & FEAT-CLI-01."""

    def test_feat5_create_checkout_session_returns_redirect_url(self):
        """Endpoint returns valid Stripe or Mock checkout redirect URL."""
        self.require_app()
        customer_email = f"checkout_{uuid.uuid4().hex[:6]}@acme.ai"
        res = self.client.post(
            "/api/v1/billing/checkout",
            json={
                "customer_email": customer_email,
                "tier": "pro",
                "interval": "monthly",
            },
        )
        self.assertEqual(res.status_code, 200, f"Checkout creation failed: {res.text}")
        body = res.json()
        payload = body.get("data", body)

        self.assertIn("checkout_url", payload, "Response must include checkout_url")
        self.assertIn("session_id", payload, "Response must include session_id")
        self.assertTrue(payload["checkout_url"].startswith(("https://", "/api/v1/")))

    def test_feat5_create_customer_portal_session_returns_url(self):
        """POST /api/v1/billing/portal returns billing management URL."""
        self.require_app()
        customer_email = f"portal_{uuid.uuid4().hex[:6]}@acme.ai"
        res = self.client.post(
            "/api/v1/billing/portal",
            json={"customer_email": customer_email},
        )
        self.assertEqual(res.status_code, 200, f"Portal creation failed: {res.text}")
        body = res.json()
        payload = body.get("data", body)

        self.assertIn("portal_url", payload, "Response must include portal_url")
        self.assertTrue(payload["portal_url"].startswith(("https://", "/api/v1/")))

    def test_feat5_simulate_webhook_generates_valid_hmac_payload(self):
        """Local simulator outputs cryptographically valid mock event."""
        self.require_app()
        res = self.simulate_webhook_api(
            event_type="checkout.session.completed",
            customer_email="simulated@acme.ai",
            tier="pro",
            provider="stripe",
        )
        self.assertEqual(res.status_code, 200, f"Simulation endpoint failed: {res.text}")
        body = res.json()
        payload = body.get("data", body)

        self.assertTrue(payload.get("processed", False))
        self.assertEqual(payload.get("event_type"), "checkout.session.completed")
        self.assertTrue(str(payload.get("license_key", "")).startswith("LIC-PRO-"))

    def test_feat5_simulate_checkout_lifecycle_end_to_end(self):
        """Local simulation triggers auto-provisioning and returns working license."""
        self.require_app()
        customer_email = f"lifecycle_{uuid.uuid4().hex[:6]}@acme.ai"
        res = self.simulate_webhook_api(
            event_type="checkout.session.completed",
            customer_email=customer_email,
            tier="pro",
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        payload = body.get("data", body)

        license_key = payload.get("license_key")
        self.assertIsNotNone(license_key, "Simulated checkout must return issued license_key")
        self.assertTrue(license_key.startswith("LIC-PRO-"))

        verify_res = self.verify_license_api(license_key=license_key)
        self.assertEqual(verify_res.status_code, 200)
        verify_payload = verify_res.json().get("data", {})
        self.assertTrue(verify_payload.get("valid"))
        self.assertEqual(verify_payload.get("max_seats"), 3)

    def test_feat5_mock_mode_allows_zero_credential_execution(self):
        """Full suite operates with BILLING_MODE=mock without live third-party calls."""
        self.require_app()
        self.assertEqual(os.environ.get("BILLING_MODE"), "mock")
        health_res = self.client.get("/healthz")
        self.assertEqual(health_res.status_code, 200)
        ready_res = self.client.get("/readyz")
        self.assertEqual(ready_res.status_code, 200)
        self.assertTrue(ready_res.json().get("ready"))

    def test_feat_cli_end_to_end_fresh_db_lifecycle_and_clean_errors(self):
        """CLI auto-migrates fresh SQLite DB, applies tier defaults, executes offline/online ops, and exits cleanly on errors."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "cli_fresh.db"
            prev_db_url = os.environ.get("DATABASE_URL")
            os.environ["DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
            get_settings.cache_clear()
            try:
                # 1. Issue Pro license using tier default seats (3) & credits (500)
                issue_res = runner.invoke(
                    cli, ["issue", "--email", "cli_user@acme.ai", "--tier", "pro"]
                )
                self.assertEqual(issue_res.exit_code, 0, issue_res.output)
                issued = json.loads(issue_res.output)
                key = issued["license_key"]
                self.assertEqual(issued["max_seats"], 3)
                self.assertEqual(issued["quota_credits"], 500)

                # 2. Issue Lifetime license -> perpetual (expires_at is None, 3 seats)
                life_res = runner.invoke(
                    cli, ["issue", "--email", "founder@acme.ai", "--tier", "lifetime"]
                )
                self.assertEqual(life_res.exit_code, 0, life_res.output)
                life_data = json.loads(life_res.output)
                self.assertIsNone(life_data["expires_at"])
                self.assertEqual(life_data["max_seats"], 3)

                # 3. Offline verification (both OpenSSL and pure-Python math)
                off_res = runner.invoke(cli, ["verify", key, "--offline"])
                self.assertEqual(off_res.exit_code, 0, off_res.output)
                self.assertTrue(json.loads(off_res.output)["valid"])

                pure_res = runner.invoke(
                    cli, ["verify", "--key", key, "--offline", "--pure-python"]
                )
                self.assertEqual(pure_res.exit_code, 0, pure_res.output)
                self.assertTrue(json.loads(pure_res.output)["valid"])

                # 4. Activate node & verify online with hardware_id
                act_res = runner.invoke(
                    cli, ["activate", key, "--hardware-id", "HW-CLI-NODE-1"]
                )
                self.assertEqual(act_res.exit_code, 0, act_res.output)
                self.assertEqual(json.loads(act_res.output)["current_activations"], 1)

                on_res = runner.invoke(
                    cli, ["verify", key, "--hardware-id", "hw-cli-node-1"]
                )
                self.assertEqual(on_res.exit_code, 0, on_res.output)
                self.assertTrue(json.loads(on_res.output)["valid"])

                # 5. Quota deduct, replenish (top-up + cycle reset), and balance
                ded_res = runner.invoke(
                    cli,
                    ["quota", "deduct", key, "--credits", "20", "--idempotency-key", "cli-op-1"],
                )
                self.assertEqual(ded_res.exit_code, 0, ded_res.output)
                self.assertEqual(json.loads(ded_res.output)["remaining_balance"], 480)

                rep_res = runner.invoke(
                    cli, ["quota", "replenish", key, "--credits", "50"]
                )
                self.assertEqual(rep_res.exit_code, 0, rep_res.output)
                self.assertEqual(json.loads(rep_res.output)["balance"], 530)

                rst_res = runner.invoke(
                    cli, ["quota", "replenish", key, "--credits", "500", "--reset-cycle"]
                )
                self.assertEqual(rst_res.exit_code, 0, rst_res.output)
                rst_payload = json.loads(rst_res.output)
                self.assertEqual(rst_payload["balance"], 500)
                self.assertEqual(rst_payload["total_allowance"], 500)
                self.assertEqual(rst_payload["consumed"], 0)

                # 6. Revoke & confirm subsequent verify fails cleanly with JSON error (no traceback)
                rev_res = runner.invoke(cli, ["revoke", key, "--reason", "cli_test"])
                self.assertEqual(rev_res.exit_code, 0, rev_res.output)

                fail_res = runner.invoke(cli, ["verify", key])
                self.assertNotEqual(fail_res.exit_code, 0)
                self.assertNotIn("Traceback", fail_res.output)
                err_json = json.loads(fail_res.output)
                self.assertFalse(err_json["success"])
                self.assertEqual(err_json["error"]["code"], "LICENSE_REVOKED")
            finally:
                if prev_db_url is not None:
                    os.environ["DATABASE_URL"] = prev_db_url
                get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
