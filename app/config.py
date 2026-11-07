"""Application configuration using Pydantic Settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


_INSECURE_SECRET_KEYS = frozenset({
    "",
    "test_super_secret_key_32_characters_long_1234",
    "change_me_super_secret_hmac_key_at_least_32_bytes_long_1234",
    "default_secret_key_at_least_16_bytes_long",
})
_INSECURE_ED25519_PRIVATE_KEYS = frozenset({
    "",
    "a01fd194d15178191f62e570962a579e61bf728945f79655d9df145eada811ec",
})
_INSECURE_WEBHOOK_SECRETS = frozenset({
    "",
    "whsec_test_stripe_secret_12345",
    "whsec_test_lemonsqueezy_secret_12345",
})
_INSECURE_ADMIN_KEYS = frozenset({
    "",
    "kf_dev_admin_key_change_in_prod",
})


_PROXY_MODES = frozenset({"fly", "cloudflare", "standard", "direct"})


class Settings(BaseSettings):
    """Central configuration for KeyFlint."""

    DATABASE_URL: str = "sqlite:///data/keyforge.db"
    SECRET_KEY: str = "test_super_secret_key_32_characters_long_1234"
    ED25519_PRIVATE_KEY_HEX: Optional[str] = "a01fd194d15178191f62e570962a579e61bf728945f79655d9df145eada811ec"
    # Derived from ED25519_PRIVATE_KEY_HEX when unset; if set, it must match the private key.
    ED25519_PUBLIC_KEY_HEX: Optional[str] = None
    # Key rotation (v1.1). ED25519_KID unset = legacy tokens without "kid" (v1.0 compatible).
    ED25519_KID: Optional[str] = None
    # Retired verification keys kept for old tokens: "kid=hex,kid2=hex" or bare "hex" (pre-kid key).
    ED25519_RETIRED_PUBLIC_KEYS: Optional[str] = None
    # Seconds after a deduct during which /quota/refund may compensate it (0 disables refunds).
    QUOTA_REFUND_WINDOW_SECONDS: int = 900
    # Refund circuit breaker (per license): deny automatic refunds when more than
    # REFUND_BREAKER_MAX_CONSECUTIVE refunds in a row happen within REFUND_BREAKER_WINDOW_SECONDS,
    # or when refunds exceed REFUND_BREAKER_MAX_RATIO of the last REFUND_BREAKER_SAMPLE deducts
    # (only once REFUND_BREAKER_MIN_SAMPLE deducts exist), or refunded credits exceed
    # REFUND_BREAKER_MAX_CREDIT_RATIO of the credits in that sample (v1.2.2; 1 disables that rule).
    # REFUND_BREAKER_ENABLED=false turns it off.
    REFUND_BREAKER_ENABLED: bool = True
    REFUND_BREAKER_MAX_CONSECUTIVE: int = 5
    REFUND_BREAKER_WINDOW_SECONDS: int = 600
    REFUND_BREAKER_MAX_RATIO: float = 0.25
    REFUND_BREAKER_SAMPLE: int = 50
    REFUND_BREAKER_MIN_SAMPLE: int = 10
    REFUND_BREAKER_MAX_CREDIT_RATIO: float = 0.25
    # Self-service node release: max releases per license in any 24 h window (0 disables the endpoint).
    NODE_RELEASES_PER_24H: int = 1

    STRIPE_WEBHOOK_SECRET: str = "whsec_test_stripe_secret_12345"
    LEMONSQUEEZY_WEBHOOK_SECRET: str = "whsec_test_lemonsqueezy_secret_12345"
    STRIPE_SECRET_KEY: Optional[str] = None
    LEMONSQUEEZY_CHECKOUT_URL: Optional[str] = None
    CHECKOUT_SUCCESS_URL: str = "http://127.0.0.1:8000/?checkout=success"
    CHECKOUT_CANCEL_URL: str = "http://127.0.0.1:8000/?checkout=cancelled"
    BILLING_PORTAL_RETURN_URL: str = "http://127.0.0.1:8000/"
    # Base URL of the page that redeems portal magic links (the gateway serving the portal UI).
    # Never derived from the request Host header (it would let an attacker redirect the link).
    PORTAL_LINK_BASE_URL: str = "http://127.0.0.1:8000/"
    PORTAL_LINK_TTL_SECONDS: int = 900
    # How long a Stripe Checkout session id can reveal its license on the buyer's success page.
    CHECKOUT_REVEAL_TTL_SECONDS: int = 86400
    PORTAL_LINK_MAX_PER_WINDOW: int = 3  # magic links per customer per TTL window (anti email-bombing)
    # Self-serve free trial: one Community license (Tier.COMMUNITY credits) per email, emailed to that inbox.
    TRIAL_ENABLED: bool = False
    TRIAL_DAILY_CAP: int = 100  # trial licenses per process per 24 h (cost ceiling)

    # Pay-as-you-go top-ups: credits added to an existing license (same key) via a dynamic Stripe Checkout.
    TOPUP_ENABLED: bool = True
    TOPUP_MAX_PER_LICENSE_DAY: int = 3
    TOPUP_REQUIRE_TOS_CONSENT: bool = False  # Enabled in Stripe Dashboard under Public Details
    TOPUP_TAX_BEHAVIOR: str = "inclusive"  # "inclusive" (price shown = price paid), "exclusive" or "" (account default)
    TOPUP_TAX_CODE: str = "txcd_10202003"  # same code as the existing KeyFlint products (Managed Payments eligible)
    TOPUP_MANAGED_PAYMENTS: bool = True
    TOPUP_STRIPE_API_VERSION: str = "2025-03-31.basil"  # managed_payments needs basil or later
    TOPUP_RETURN_ORIGINS: str = "https://mcp.keyflint.dev,https://keyflint.dev"
    TOPUP_DEFAULT_RETURN_URL: str = "https://mcp.keyflint.dev/saldo/"
    ADMIN_API_KEY: str = "kf_dev_admin_key_change_in_prod"

    # Transactional Email Dispatch (Resend / SMTP)
    EMAIL_ENABLED: bool = False
    EMAIL_FROM: str = "KeyFlint <licenses@keyflint.dev>"
    RESEND_API_KEY: Optional[str] = None
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_USE_TLS: bool = True
    EMAIL_RETRY_INTERVAL_SECONDS: int = 300  # 0 disables the automatic retry loop
    OPS_ALERT_EMAIL: Optional[str] = None  # operator inbox for billing incidents; unset = log only
    # "Credits ran out" retention email (trial / MCP-hub licenses only; once per depletion episode)
    DEPLETION_EMAIL_ENABLED: bool = True
    DEPLETION_EMAIL_COOLDOWN_DAYS: int = 25  # same episode (no credits added) never re-sends before this
    DEPLETION_EMAIL_TOPUP_EUR: int = 5  # amount preselected by the email's one-click link

    # Backup verification: restore the Litestream replica to a temp file and compare row counts.
    BACKUP_CHECK_INTERVAL_SECONDS: int = 3600  # 0 disables it
    BACKUP_HEARTBEAT_URL: Optional[str] = None  # healthchecks.io-style ping URL (+ "/fail" on failure)

    # Hourly SQLite maintenance (0 disables). Usage events are the usage history and the idempotency
    # ledger, so they are kept forever unless USAGE_EVENTS_RETENTION_DAYS is set (minimum 30).
    MAINTENANCE_INTERVAL_SECONDS: int = 3600
    USAGE_EVENTS_RETENTION_DAYS: int = 0

    BILLING_MODE: str = "mock"
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    MAX_PAYLOAD_BYTES: int = 65536
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 25
    RATE_LIMIT_WEBHOOK_REQUESTS: int = 300
    RATE_LIMIT_WINDOW_SECONDS: int = 10
    TRUST_PROXY_HEADERS: bool = False  # legacy alias: true = TRUSTED_PROXY_MODE "fly"
    # Where the client IP comes from (rate limiting): fly | cloudflare | standard | direct.
    # Unset = "fly" if TRUST_PROXY_HEADERS else "direct".
    TRUSTED_PROXY_MODE: Optional[str] = None
    # Comma-separated IPs/CIDRs of your own proxies ("standard" and "cloudflare" modes).
    # Empty = loopback and private ranges (a proxy in the same Docker/VPC network).
    TRUSTED_PROXY_IPS: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def proxy_mode(self) -> str:
        mode = (self.TRUSTED_PROXY_MODE or "").strip().lower()
        if not mode:
            return "fly" if self.TRUST_PROXY_HEADERS else "direct"
        if mode not in _PROXY_MODES:
            raise ValueError(
                f"TRUSTED_PROXY_MODE must be one of {', '.join(sorted(_PROXY_MODES))}; got {mode!r}"
            )
        return mode

    @property
    def DATABASE_PATH(self) -> str | Path:
        """Extract filesystem path or in-memory specifier from DATABASE_URL."""
        url = self.DATABASE_URL.strip()
        if url == "sqlite:///:memory:" or url == ":memory:":
            return ":memory:"
        if url.startswith("sqlite:///"):
            raw_path = url[len("sqlite:///"):]
            return Path(raw_path)
        if url.startswith("sqlite://"):
            raw_path = url[len("sqlite://"):]
            return Path(raw_path)
        return Path(url)

    def validate_production_secrets(self) -> None:
        """Fails fast when ENVIRONMENT='production' is started with public default or weak secrets."""
        if self.ENVIRONMENT.strip().lower() != "production":
            return

        problems: list[str] = []
        if self.SECRET_KEY in _INSECURE_SECRET_KEYS or len(self.SECRET_KEY.encode("utf-8")) < 32:
            problems.append("SECRET_KEY must be a non-default secret >= 32 bytes")

        priv = (self.ED25519_PRIVATE_KEY_HEX or "").strip().lower()
        if priv in _INSECURE_ED25519_PRIVATE_KEYS or len(priv) != 64:
            problems.append("ED25519_PRIVATE_KEY_HEX must be a unique 64-hex-char private key")
        else:
            try:
                bytes.fromhex(priv)
            except ValueError:
                problems.append("ED25519_PRIVATE_KEY_HEX is not valid hexadecimal")
            else:
                pub = (self.ED25519_PUBLIC_KEY_HEX or "").strip().lower()
                if pub:
                    from app.infrastructure.security.ed25519_signer import Ed25519Signer
                    try:
                        Ed25519Signer(private_key_hex=priv, public_key_hex=pub)
                    except ValueError:
                        problems.append("ED25519_PUBLIC_KEY_HEX does not match ED25519_PRIVATE_KEY_HEX (leave it empty to derive it)")

        if self.STRIPE_WEBHOOK_SECRET in _INSECURE_WEBHOOK_SECRETS:
            problems.append("STRIPE_WEBHOOK_SECRET must not use test default in production")

        if self.LEMONSQUEEZY_WEBHOOK_SECRET in _INSECURE_WEBHOOK_SECRETS:
            problems.append("LEMONSQUEEZY_WEBHOOK_SECRET must not use test default in production")

        if self.ADMIN_API_KEY in _INSECURE_ADMIN_KEYS or len(self.ADMIN_API_KEY) < 16:
            problems.append("ADMIN_API_KEY must be a strong non-default key >= 16 chars")

        if problems:
            raise RuntimeError(
                "Refusing to start in production with insecure configuration: " + "; ".join(problems)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns singleton cached instance of application settings."""
    return Settings()
