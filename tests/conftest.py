"""KeyForge E2E Automated Test Infrastructure & Fixtures.

Provides in-memory SQLite persistence, Starlette TestClient, cryptographic helper utilities,
deterministic keypairs, signature generators, and BaseKeyForgeTestCase.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
import sqlite3
import unittest
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Test Environment Variables Configuration
TEST_SECRET_KEY = "test_super_secret_key_32_characters_long_1234"
TEST_ED25519_PRIVATE_KEY_HEX = "a01fd194d15178191f62e570962a579e61bf728945f79655d9df145eada811ec"
TEST_ED25519_PUBLIC_KEY_HEX = "0043b567534bfa2d55059a05642f75573d420899146f334a9f7fc5fba797bd0b"

ROGUE_ED25519_PRIVATE_KEY_HEX = "c87b222e5a705cf4b761ac9efb0b1cd51c4342ac00ff0379cb52a91e4335c711"
ROGUE_ED25519_PUBLIC_KEY_HEX = "65f395155b4f985e1ec19869584974ae50b554a3993b0902b241eb1284e8ed99"

TEST_STRIPE_WEBHOOK_SECRET = "whsec_test_stripe_secret_12345"
TEST_LEMONSQUEEZY_WEBHOOK_SECRET = "whsec_test_lemonsqueezy_secret_12345"

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = TEST_SECRET_KEY
os.environ["ED25519_PRIVATE_KEY_HEX"] = TEST_ED25519_PRIVATE_KEY_HEX
os.environ["ED25519_PUBLIC_KEY_HEX"] = TEST_ED25519_PUBLIC_KEY_HEX
os.environ["STRIPE_WEBHOOK_SECRET"] = TEST_STRIPE_WEBHOOK_SECRET
os.environ["LEMONSQUEEZY_WEBHOOK_SECRET"] = TEST_LEMONSQUEEZY_WEBHOOK_SECRET
os.environ["BILLING_MODE"] = "mock"
os.environ["ENVIRONMENT"] = "testing"

# SQLite Schema Definition (Hexagonal Clean Architecture Contract)
TEST_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    company TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);

CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    license_key TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL CHECK(tier IN ('community', 'pro', 'studio', 'lifetime')),
    status TEXT NOT NULL CHECK(status IN ('active', 'suspended', 'expired', 'revoked', 'grace_period')),
    max_seats INTEGER NOT NULL DEFAULT 1,
    current_activations INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    signature TEXT NOT NULL,
    features TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_licenses_key ON licenses(license_key);
CREATE INDEX IF NOT EXISTS idx_licenses_customer ON licenses(customer_id);
CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);

CREATE TABLE IF NOT EXISTS activations (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    hardware_id TEXT NOT NULL,
    machine_name TEXT,
    ip_address TEXT,
    activated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(license_id, hardware_id)
);
CREATE INDEX IF NOT EXISTS idx_activations_license ON activations(license_id);

CREATE TABLE IF NOT EXISTS quotas (
    id TEXT PRIMARY KEY,
    license_id TEXT UNIQUE NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    total_allowance INTEGER NOT NULL DEFAULT 1000,
    balance INTEGER NOT NULL DEFAULT 1000,
    consumed INTEGER NOT NULL DEFAULT 0,
    last_reset_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_quotas_license ON quotas(license_id);

CREATE TABLE IF NOT EXISTS usage_events (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    credits_consumed INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    metadata_json TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(license_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_usage_license ON usage_events(license_id);
CREATE INDEX IF NOT EXISTS idx_usage_idempotency ON usage_events(license_id, idempotency_key);

CREATE TABLE IF NOT EXISTS webhook_events (
    id TEXT PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('stripe', 'lemonsqueezy')),
    event_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processed', 'failed', 'ignored')),
    processed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_webhooks_event_id ON webhook_events(event_id);

CREATE TABLE IF NOT EXISTS revoked_licenses (
    license_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    revoked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


# ==============================================================================
# Cryptographic and Encoding Helper Utilities
# ==============================================================================

def b64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def b64url_decode(s: str) -> bytes:
    """Base64url decode with padding compensation."""
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + padding)


def decode_license_token(token: str) -> Tuple[str, Dict[str, Any], str]:
    """Parse a KeyForge license token into (tier, payload_dict, signature_b64).
    
    Format: LIC-<TIER>-<BASE64URL_PAYLOAD>.<BASE64URL_SIGNATURE>
    """
    if not token or not token.startswith("LIC-"):
        raise ValueError(f"Invalid license prefix: {token}")
    
    parts = token.split("-", 2)
    if len(parts) < 3:
        raise ValueError(f"Malformed token structure: {token}")
    
    tier = parts[1].lower()
    body_and_sig = parts[2]
    
    if "." not in body_and_sig:
        raise ValueError(f"Missing dot delimiter: {token}")
    
    payload_b64, sig_b64 = body_and_sig.split(".", 1)
    payload_json = b64url_decode(payload_b64).decode("utf-8")
    payload = json.loads(payload_json)
    return tier, payload, sig_b64


def encode_license_token(tier: str, payload: Dict[str, Any], sig_b64: str) -> str:
    """Build a KeyForge license token from components."""
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = b64url_encode(payload_json.encode("utf-8"))
    return f"LIC-{tier.upper()}-{payload_b64}.{sig_b64}"


def sign_payload_ed25519(payload: Dict[str, Any], private_key_hex: str = TEST_ED25519_PRIVATE_KEY_HEX) -> str:
    """Sign payload dictionary with Ed25519 private key, returning base64url signature."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    raw_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = priv.sign(raw_bytes)
    return b64url_encode(sig)


def verify_payload_ed25519(payload: Dict[str, Any], signature_b64: str, public_key_hex: str = TEST_ED25519_PUBLIC_KEY_HEX) -> bool:
    """Verify Ed25519 signature over payload dictionary."""
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.exceptions import InvalidSignature
    try:
        pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        raw_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = b64url_decode(signature_b64)
        pub.verify(sig, raw_bytes)
        return True
    except (InvalidSignature, Exception):
        return False


def sign_payload_hmac(payload: Dict[str, Any], secret: str = TEST_SECRET_KEY) -> str:
    """Sign payload dictionary using HMAC-SHA256, returning base64url signature."""
    raw_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    h = hmac.new(secret.encode("utf-8"), raw_bytes, hashlib.sha256).digest()
    return b64url_encode(h)


def verify_payload_hmac(payload: Dict[str, Any], signature_b64: str, secret: str = TEST_SECRET_KEY) -> bool:
    """Verify HMAC-SHA256 signature in constant time."""
    expected = sign_payload_hmac(payload, secret)
    return hmac.compare_digest(expected, signature_b64)


def generate_stripe_signature(raw_body: bytes, secret: str = TEST_STRIPE_WEBHOOK_SECRET, timestamp: Optional[int] = None) -> str:
    """Generate Stripe-Signature header format: t={timestamp},v1={hex_signature}."""
    if timestamp is None:
        timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def generate_lemonsqueezy_signature(raw_body: bytes, secret: str = TEST_LEMONSQUEEZY_WEBHOOK_SECRET) -> str:
    """Generate X-Signature header for LemonSqueezy."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


# ==============================================================================
# Database Helper
# ==============================================================================

def create_in_memory_db() -> sqlite3.Connection:
    """Initialize an in-memory SQLite database populated with KeyForge schemas."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(TEST_SCHEMA_SQL)
    conn.commit()
    return conn


# ==============================================================================
# Base Test Case Class (Standard library unittest + Starlette TestClient)
# ==============================================================================

class BaseKeyForgeTestCase(unittest.TestCase):
    """Base test case providing clean isolation, in-memory DB, TestClient, and helpers."""

    client = None
    app = None
    db: sqlite3.Connection = None

    @classmethod
    def setUpClass(cls):
        # Configure environment
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        os.environ["SECRET_KEY"] = TEST_SECRET_KEY
        os.environ["ED25519_PRIVATE_KEY_HEX"] = TEST_ED25519_PRIVATE_KEY_HEX
        os.environ["ED25519_PUBLIC_KEY_HEX"] = TEST_ED25519_PUBLIC_KEY_HEX
        os.environ["STRIPE_WEBHOOK_SECRET"] = TEST_STRIPE_WEBHOOK_SECRET
        os.environ["LEMONSQUEEZY_WEBHOOK_SECRET"] = TEST_LEMONSQUEEZY_WEBHOOK_SECRET
        os.environ["BILLING_MODE"] = "mock"
        os.environ["ENVIRONMENT"] = "testing"

    def setUp(self):
        """Set up fresh in-memory database and test client for each test."""
        from app.config import get_settings
        from app.infrastructure.database.connection import reset_shared_memory_db
        from app.presentation.middlewares import rate_limiter

        get_settings.cache_clear()
        reset_shared_memory_db()
        rate_limiter.reset()
        self.db = create_in_memory_db()

        # Attempt to import application; if available, create TestClient
        try:
            import warnings
            from app.main import app
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r".*Using `httpx` with `starlette\.testclient` is deprecated.*",
                    category=Warning,
                )
                from starlette.testclient import TestClient
                self.app = app
                self.client = TestClient(app, raise_server_exceptions=False)
        except ImportError:
            self.app = None
            self.client = None

    def tearDown(self):
        """Clean up database connection."""
        if self.db:
            try:
                self.db.close()
            except Exception:
                pass

    def require_app(self):
        """Helper to ensure application is present when running E2E HTTP assertions."""
        if self.client is None or self.app is None:
            self.fail("KeyForge application ('app.main') is not yet implemented or could not be imported.")

    # --------------------------------------------------------------------------
    # Common Test Helpers (Opaque-box orchestration)
    # --------------------------------------------------------------------------

    def issue_license_api(
        self,
        customer_email: str = "alex@acme.ai",
        tier: str = "pro",
        max_seats: int = 1,
        expires_in_days: int = 365,
        features: Optional[list] = None,
        signing_algorithm: str = "ed25519"
    ) -> Dict[str, Any]:
        """Issue a license through the REST API or fail if not implemented."""
        self.require_app()
        payload = {
            "customer_email": customer_email,
            "tier": tier,
            "max_seats": max_seats,
            "expires_in_days": expires_in_days,
            "features": features or ["core", "cli_offline"],
            "signing_algorithm": signing_algorithm,
        }
        res = self.client.post("/api/v1/licenses/issue", json=payload)
        self.assertIn(res.status_code, (200, 201), f"Issue license failed: {res.text}")
        data = res.json()
        return data.get("data", data)

    def verify_license_api(
        self,
        license_key: str,
        hardware_id: Optional[str] = None,
        domain: Optional[str] = None
    ) -> Any:
        """Verify a license through the REST API."""
        self.require_app()
        payload = {"license_key": license_key}
        if hardware_id:
            payload["hardware_id"] = hardware_id
        if domain:
            payload["domain"] = domain
        return self.client.post("/api/v1/licenses/verify", json=payload)

    def activate_license_api(
        self,
        license_key: str,
        hardware_id: str = "hw-test-node-1",
        machine_name: str = "macbook-pro"
    ) -> Any:
        """Activate a machine on a license through the REST API."""
        self.require_app()
        payload = {
            "license_key": license_key,
            "hardware_id": hardware_id,
            "machine_name": machine_name
        }
        return self.client.post("/api/v1/licenses/activate", json=payload)

    def deduct_quota_api(
        self,
        license_key: str,
        credits: int = 5,
        idempotency_key: Optional[str] = None,
        event_type: str = "ai_prompt_tokens",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Deduct credits through the REST API."""
        self.require_app()
        payload = {
            "license_key": license_key,
            "credits": credits,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
            "event_type": event_type,
            "metadata": metadata or {}
        }
        return self.client.post("/api/v1/quota/deduct", json=payload)

    def simulate_webhook_api(
        self,
        event_type: str = "checkout.session.completed",
        tier: str = "pro",
        customer_email: str = "alex@acme.ai",
        provider: str = "stripe"
    ) -> Any:
        """Simulate a payment gateway webhook via local simulator endpoint."""
        self.require_app()
        payload = {
            "provider": provider,
            "event_type": event_type,
            "customer_email": customer_email,
            "tier": tier
        }
        return self.client.post("/api/v1/billing/simulate-webhook", json=payload)
