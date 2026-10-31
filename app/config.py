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


class Settings(BaseSettings):
    """Central configuration for KeyForge."""

    DATABASE_URL: str = "sqlite:///data/keyforge.db"
    SECRET_KEY: str = "test_super_secret_key_32_characters_long_1234"
    ED25519_PRIVATE_KEY_HEX: Optional[str] = "a01fd194d15178191f62e570962a579e61bf728945f79655d9df145eada811ec"
    ED25519_PUBLIC_KEY_HEX: Optional[str] = "0043b567534bfa2d55059a05642f75573d420899146f334a9f7fc5fba797bd0b"

    STRIPE_WEBHOOK_SECRET: str = "whsec_test_stripe_secret_12345"
    LEMONSQUEEZY_WEBHOOK_SECRET: str = "whsec_test_lemonsqueezy_secret_12345"
    STRIPE_SECRET_KEY: Optional[str] = None
    LEMONSQUEEZY_CHECKOUT_URL: Optional[str] = None
    CHECKOUT_SUCCESS_URL: str = "http://127.0.0.1:8000/?checkout=success"
    CHECKOUT_CANCEL_URL: str = "http://127.0.0.1:8000/?checkout=cancelled"
    BILLING_PORTAL_RETURN_URL: str = "http://127.0.0.1:8000/"
    ADMIN_API_KEY: str = "kf_dev_admin_key_change_in_prod"

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
    TRUST_PROXY_HEADERS: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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
