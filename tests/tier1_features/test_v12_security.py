"""Tier 1: v1.2 security — refund circuit breaker, TRUSTED_PROXY_MODE, self-service node release."""

from __future__ import annotations

import os
import uuid

from tests.conftest import BaseKeyFlintTestCase

_ENV = ("REFUND_BREAKER_ENABLED", "REFUND_BREAKER_MIN_SAMPLE", "REFUND_BREAKER_MAX_CREDIT_RATIO",
        "NODE_RELEASES_PER_24H")


class _EnvCase(BaseKeyFlintTestCase):
    def tearDown(self):
        for k in _ENV:
            os.environ.pop(k, None)
        from app.config import get_settings
        get_settings.cache_clear()
        super().tearDown()

    def _env(self, **kv):
        from app.config import get_settings
        for k, v in kv.items():
            os.environ[k] = str(v)
        get_settings.cache_clear()


class TestRefundCircuitBreaker(_EnvCase):
    def _cycle(self, key: str, refund: bool):
        ik = str(uuid.uuid4())
        self.assertEqual(self.deduct_quota_api(key, credits=2, idempotency_key=ik).status_code, 200)
        if refund:
            return self.client.post("/api/v1/quota/refund", json={"license_key": key, "idempotency_key": ik})
        return None

    def _events(self, key: str):
        from app.infrastructure.database.connection import get_shared_memory_holder
        from app.infrastructure.repositories.sqlite_quota_repo import SqliteQuotaRepo
        lic = self.client.post("/api/v1/licenses/verify", json={"license_key": key}).json()["data"]["license_id"]
        return SqliteQuotaRepo(get_shared_memory_holder()).list_license_events(lic)

    def test_sixth_consecutive_refund_is_denied_and_audited(self):
        key = self.issue_license_api(customer_email="abuse@acme.ai")["license_key"]
        for _ in range(5):
            self.assertEqual(self._cycle(key, refund=True).status_code, 200)
        before = self.client.get("/api/v1/quota/balance", params={"license_key": key}).json()["data"]["balance"]
        res = self._cycle(key, refund=True)
        self.assertEqual(res.status_code, 429, res.text)
        self.assertEqual(res.json()["error"]["code"], "REFUND_VELOCITY_EXCEEDED")
        after = self.client.get("/api/v1/quota/balance", params={"license_key": key}).json()["data"]["balance"]
        self.assertEqual(after, before - 2)  # the credits stay charged
        events = self._events(key)
        self.assertEqual(events[0]["event_type"], "refund_velocity_exceeded")
        self.assertEqual(events[0]["details"]["rule"], "consecutive")

    def test_charged_call_resets_the_consecutive_run(self):
        key = self.issue_license_api(customer_email="flaky@acme.ai")["license_key"]
        self._env(REFUND_BREAKER_MIN_SAMPLE=1000)  # isolate the consecutive rule
        for _ in range(4):
            self.assertEqual(self._cycle(key, refund=True).status_code, 200)
        self._cycle(key, refund=False)
        for _ in range(4):
            self.assertEqual(self._cycle(key, refund=True).status_code, 200)

    def test_ratio_rule_over_sample(self):
        key = self.issue_license_api(customer_email="ratio@acme.ai")["license_key"]
        for _ in range(8):
            self._cycle(key, refund=False)
        self.assertEqual(self._cycle(key, refund=True).status_code, 200)   # 9 deducts < min sample
        self.assertEqual(self._cycle(key, refund=True).status_code, 200)   # (1+1)/10 = 20%
        self.assertEqual(self._cycle(key, refund=True).status_code, 429)   # (2+1)/11 = 27% > 25%
        self.assertEqual(self._events(key)[0]["details"]["rule"], "ratio")

    def _deduct(self, key: str, credits: int) -> str:
        ik = str(uuid.uuid4())
        self.assertEqual(self.deduct_quota_api(key, credits=credits, idempotency_key=ik).status_code, 200)
        return ik

    def _refund(self, key: str, ik: str):
        return self.client.post("/api/v1/quota/refund", json={"license_key": key, "idempotency_key": ik})

    def test_cheap_calls_cannot_dilute_expensive_refunds(self):
        """v1.2.2: padding with 1-credit calls keeps the count ratio low; the credit ratio still trips."""
        key = self.issue_license_api(customer_email="dilute@acme.ai")["license_key"]
        for _ in range(5):
            self._deduct(key, 1)
        self.assertEqual(self._refund(key, self._deduct(key, 50)).status_code, 200)  # 6 deducts < min sample
        for _ in range(5):
            self._deduct(key, 1)
        before = self.client.get("/api/v1/quota/balance", params={"license_key": key}).json()["data"]["balance"]
        res = self._refund(key, self._deduct(key, 50))  # count (1+1)/12 = 17 %, credits (50+50)/110 = 91 %
        self.assertEqual(res.status_code, 429, res.text)
        self.assertEqual(res.json()["error"]["code"], "REFUND_VELOCITY_EXCEEDED")
        after = self.client.get("/api/v1/quota/balance", params={"license_key": key}).json()["data"]["balance"]
        self.assertEqual(after, before - 50)  # the credits stay charged
        details = self._events(key)[0]["details"]
        self.assertEqual(details["rule"], "credit_ratio")
        self.assertEqual((details["refunded_credits"], details["deducted_credits"]), (100, 110))

    def test_rare_cheap_refund_among_expensive_calls_passes(self):
        key = self.issue_license_api(customer_email="mixed@acme.ai")["license_key"]
        for _ in range(12):
            self._deduct(key, 30)
        self.assertEqual(self._refund(key, self._deduct(key, 1)).status_code, 200)

    def test_credit_ratio_can_be_relaxed(self):
        self._env(REFUND_BREAKER_MAX_CREDIT_RATIO=1)
        key = self.issue_license_api(customer_email="relaxed@acme.ai")["license_key"]
        for _ in range(10):
            self._deduct(key, 1)
        self.assertEqual(self._refund(key, self._deduct(key, 50)).status_code, 200)

    def test_breaker_can_be_disabled(self):
        self._env(REFUND_BREAKER_ENABLED="false")
        key = self.issue_license_api(customer_email="off@acme.ai")["license_key"]
        for _ in range(7):
            self.assertEqual(self._cycle(key, refund=True).status_code, 200)

    def test_replay_of_an_accepted_refund_is_not_blocked(self):
        key = self.issue_license_api(customer_email="replay@acme.ai")["license_key"]
        ik = str(uuid.uuid4())
        self.deduct_quota_api(key, credits=1, idempotency_key=ik)
        body = {"license_key": key, "idempotency_key": ik}
        self.assertEqual(self.client.post("/api/v1/quota/refund", json=body).status_code, 200)
        for _ in range(6):
            self._cycle(key, refund=True)
        self.assertEqual(self.client.post("/api/v1/quota/refund", json=body).status_code, 200)


class TestTrustedProxyMode(_EnvCase):
    @staticmethod
    def _scope(peer, **headers):
        return {"client": (peer, 1234),
                "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]}

    def test_modes(self):
        from app.presentation.middlewares import RateLimitMiddleware
        ip = RateLimitMiddleware._extract_client_ip
        spoof = self._scope("203.0.113.9", fly_client_ip="1.1.1.1", cf_connecting_ip="2.2.2.2",
                            x_forwarded_for="3.3.3.3", x_real_ip="4.4.4.4")
        self.assertEqual(ip(spoof, mode="direct"), "203.0.113.9")
        self.assertEqual(ip(spoof, mode="fly"), "1.1.1.1")
        # Public peer is not one of our proxies: its headers are ignored.
        self.assertEqual(ip(spoof, mode="cloudflare"), "203.0.113.9")
        self.assertEqual(ip(spoof, mode="standard"), "203.0.113.9")
        self.assertEqual(ip(spoof, mode="cloudflare", trusted_proxies="203.0.113.0/24"), "2.2.2.2")

    def test_standard_skips_trusted_hops(self):
        from app.presentation.middlewares import RateLimitMiddleware
        ip = RateLimitMiddleware._extract_client_ip
        s = self._scope("172.18.0.2", x_forwarded_for="9.9.9.9, 198.51.100.4, 10.0.0.7")
        self.assertEqual(ip(s, mode="standard"), "198.51.100.4")
        self.assertEqual(ip(self._scope("127.0.0.1", x_real_ip="198.51.100.5"), mode="standard"), "198.51.100.5")
        self.assertEqual(ip(self._scope("::1"), mode="standard"), "::1")

    def test_legacy_flag_maps_to_fly_and_bad_mode_fails(self):
        from app.config import Settings
        self.assertEqual(Settings(TRUST_PROXY_HEADERS=True).proxy_mode, "fly")
        self.assertEqual(Settings().proxy_mode, "direct")
        self.assertEqual(Settings(TRUSTED_PROXY_MODE="Cloudflare").proxy_mode, "cloudflare")
        with self.assertRaises(ValueError):
            _ = Settings(TRUSTED_PROXY_MODE="nginx").proxy_mode


class TestNodeRelease(_EnvCase):
    def test_release_frees_a_seat_once_per_day(self):
        key = self.issue_license_api(customer_email="nodes@acme.ai", max_seats=1)["license_key"]
        self.assertEqual(self.activate_license_api(key, hardware_id="container-a").status_code, 200)
        self.assertNotEqual(self.activate_license_api(key, hardware_id="container-b").status_code, 200)
        nodes = self.client.post("/api/v1/licenses/nodes", json={"license_key": key}).json()["data"]
        self.assertEqual([n["hardware_id"] for n in nodes["nodes"]], ["container-a"])

        res = self.client.post("/api/v1/licenses/nodes/release",
                               json={"license_key": key, "hardware_id": "CONTAINER-A"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["data"]["current_activations"], 0)
        self.assertEqual(self.activate_license_api(key, hardware_id="container-b").status_code, 200)

        again = self.client.post("/api/v1/licenses/nodes/release",
                                 json={"license_key": key, "hardware_id": "container-b"})
        self.assertEqual(again.status_code, 429, again.text)
        self.assertEqual(again.json()["error"]["code"], "NODE_RELEASE_COOLDOWN")
        self.assertGreater(again.json()["error"]["details"]["retry_after_seconds"], 86000)

    def test_unknown_node_and_disabled(self):
        key = self.issue_license_api(customer_email="nodes2@acme.ai")["license_key"]
        res = self.client.post("/api/v1/licenses/nodes/release", json={"license_key": key, "hardware_id": "x"})
        self.assertEqual(res.status_code, 404)
        self._env(NODE_RELEASES_PER_24H=0)
        self.activate_license_api(key, hardware_id="x")
        res = self.client.post("/api/v1/licenses/nodes/release", json={"license_key": key, "hardware_id": "x"})
        self.assertEqual(res.status_code, 429)

    def test_unknown_license(self):
        res = self.client.post("/api/v1/licenses/nodes", json={"license_key": "LIC-PRO-nope.nope"})
        self.assertEqual(res.status_code, 404)
