-- ============================================================================
-- KeyFlint DDL Schema
-- File: app/infrastructure/database/schemas.sql
-- ============================================================================

PRAGMA foreign_keys = ON;

-- Customers Table
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    company TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);

-- Licenses Table
CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    license_key TEXT UNIQUE NOT NULL,
    tier TEXT NOT NULL CHECK(tier IN ('community', 'indie', 'agency', 'pro', 'studio', 'lifetime')),
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

-- Machine Activations Table (Hardware/Domain Locking)
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
CREATE INDEX IF NOT EXISTS idx_activations_hardware ON activations(hardware_id);

-- Quota Ledgers Table (Token-Bucket Balance)
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

-- Usage Events Table (Audit Log & Metering)
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
-- v1.2: idx_usage_idempotency duplicated the UNIQUE(license_id, idempotency_key) index (one extra
-- B-tree write per deduct for nothing).
DROP INDEX IF EXISTS idx_usage_idempotency;

-- License Security Events (refund circuit breaker trips, node releases; manual review)
CREATE TABLE IF NOT EXISTS license_events (
    id TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_license_events_license ON license_events(license_id, event_type, created_at);

-- Webhook Events Table (Replay Protection & Idempotency)
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

-- Revoked Licenses Table
CREATE TABLE IF NOT EXISTS revoked_licenses (
    license_id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    revoked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Schema Migrations Table (Idempotent Migration Tracker)
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    checksum TEXT NOT NULL
);
