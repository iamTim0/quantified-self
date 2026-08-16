-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS postgis;

-- Create tenants table (Workspace / Organization level)
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create users table (User identity level)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_tenant_id ON users (tenant_id);
CREATE INDEX idx_users_email ON users (email);

-- Create data_sources table
--
-- One row per configured connector *instance*. A tenant may hold several of the
-- same type -- three calendars, two weather locations -- so `id`, not
-- `source_type`, is what everything else refers to. `id` is already the second
-- component of every idempotency key, so two instances keep separate data with no
-- special handling anywhere downstream.
CREATE TABLE data_sources (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    source_type TEXT NOT NULL, -- e.g., 'oura', 'whoop'
    display_name VARCHAR(128) NOT NULL, -- what the user calls this instance
    config JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- Two instances of a type are the point; two with the same name are not.
    CONSTRAINT uq_data_sources_tenant_type_name UNIQUE (tenant_id, source_type, display_name)
);

-- Create data_points table
CREATE TABLE data_points (
    id UUID DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    source_id UUID NOT NULL REFERENCES data_sources(id),
    metric_type TEXT NOT NULL, -- e.g., 'sleep_score', 'hrv', 'steps'
    timestamp TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION,
    metadata JSONB DEFAULT '{}',
    embedding vector(1536), -- For AI embeddings
    location_geom geometry(Point, 4326), -- PostGIS spatial location point
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    -- TimescaleDB hypertables require the partitioning column to be part of the primary key
    PRIMARY KEY (id, timestamp),
    -- Partitioning column must also be part of any unique constraints
    UNIQUE (tenant_id, idempotency_key, timestamp)
);

-- Convert data_points to TimescaleDB hypertable partitioned on 'timestamp'
SELECT create_hypertable('data_points', 'timestamp');

-- Create indexes
CREATE INDEX idx_data_points_tenant_metric_time ON data_points (tenant_id, metric_type, timestamp DESC);
CREATE INDEX idx_data_points_tenant_source_time ON data_points (tenant_id, source_id, timestamp DESC);
CREATE INDEX idx_data_points_metadata ON data_points USING GIN (metadata);
CREATE INDEX idx_data_points_location_geom ON data_points USING GIST (location_geom);
-- What the workout list and the workout detail filter on. Partial, because most
-- rows never carry a session — a location fix, a meal, a night's sleep — and an
-- index over the whole hypertable to serve the fraction that do is paid for on
-- every write. Mirrors migration 023.
CREATE INDEX idx_data_points_tenant_session
    ON data_points (tenant_id, (metadata->>'session_id'), timestamp)
    WHERE metadata ? 'session_id';

-- Keep location_geom in step with the coordinates in `metadata`.
--
-- Migration 005 has created this trigger since PostGIS support was added, but this
-- file had only the column and the index — so a database built from init.sql alone
-- carried an empty geometry column and a GiST index over nothing, and no spatial
-- query could work. The two schema definitions have to agree.
--
-- It lives in the database rather than in the ingest consumer because every writer
-- goes through here: the consumer, the manual import endpoint and a backfill alike.
CREATE OR REPLACE FUNCTION populate_location_geom()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.metadata IS NOT NULL AND NEW.metadata ? 'latitude' AND NEW.metadata ? 'longitude' THEN
        BEGIN
            NEW.location_geom := ST_SetSRID(
                ST_MakePoint(
                    (NEW.metadata->>'longitude')::float,
                    (NEW.metadata->>'latitude')::float
                ),
                4326
            );
        EXCEPTION WHEN OTHERS THEN
            -- A coordinate that will not cast is not a reason to refuse the reading.
            NULL;
        END;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_data_points_populate_location_geom
BEFORE INSERT OR UPDATE ON data_points
FOR EACH ROW
EXECUTE FUNCTION populate_location_geom();

-- Create tenant_shares table for cross-tenant data sharing
CREATE TABLE tenant_shares (
    id UUID PRIMARY KEY,
    grantor_tenant_id UUID REFERENCES tenants(id),
    grantee_tenant_id UUID REFERENCES tenants(id),
    scope TEXT NOT NULL, -- e.g., 'read_all', 'read_metric:sleep_score'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (grantor_tenant_id, grantee_tenant_id, scope)
);

-- Which provider fields an importer read, and which it saw and did not.
--
-- The shape of what arrives, never its contents: a path, the kind of value that sat
-- there, and how often. Rolling rather than append-only, so it grows with the
-- provider's schema and not with the data — which is why it needs no retention
-- policy. Cascades from both parents, so deleting an account or a connector takes
-- its observations along.
CREATE TABLE ingest_field_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    field_path VARCHAR(512) NOT NULL,
    value_kind VARCHAR(16) NOT NULL,
    metric_type VARCHAR(128),
    occurrences INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_sync_run_id UUID,
    CONSTRAINT uq_field_reports_tenant_source_path UNIQUE (tenant_id, source_id, field_path)
);

CREATE INDEX idx_field_reports_tenant_source ON ingest_field_reports (tenant_id, source_id);
CREATE INDEX idx_field_reports_unmapped
    ON ingest_field_reports (tenant_id, source_id) WHERE metric_type IS NULL;

-- Unknown metric values stay outside data_points until the tenant resolves their
-- meaning. These are point rows, not raw provider payload archives.
CREATE TABLE metric_mapping_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    raw_metric_type VARCHAR(128) NOT NULL,
    action VARCHAR(16) NOT NULL,
    target_metric_type VARCHAR(128),
    source_unit VARCHAR(32),
    target_unit VARCHAR(32),
    aggregation VARCHAR(16),
    cadence VARCHAR(16),
    retention_days INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_metric_mapping_tenant_source_raw
        UNIQUE (tenant_id, source_id, raw_metric_type)
);

CREATE TABLE quarantined_data_points (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    raw_metric_type VARCHAR(128) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    value DOUBLE PRECISION,
    metadata JSONB NOT NULL DEFAULT '{}',
    idempotency_source_id VARCHAR(512) NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    sync_run_id UUID,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    seen_count INTEGER NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    resolution_rule_id UUID,
    CONSTRAINT uq_quarantine_tenant_source_key_time
        UNIQUE (tenant_id, source_id, idempotency_key, timestamp)
);

CREATE INDEX idx_quarantine_active_source_name
    ON quarantined_data_points (tenant_id, source_id, raw_metric_type)
    WHERE status = 'active';

CREATE TABLE quarantine_refusals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
    source_type VARCHAR(64) NOT NULL,
    raw_metric_type VARCHAR(128) NOT NULL,
    reason VARCHAR(128) NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_quarantine_refusal_tenant_source_raw_reason
        UNIQUE (tenant_id, source_id, raw_metric_type, reason)
);

-- No seed data. This file used to end by inserting a tenant and an owner account
-- with a bcrypt hash committed to the repository, which is two problems at once:
-- AGENTS.md rule 9 forbids automatic seeding, and anybody with a copy of this
-- repository had an offline target for that hash and knew the account it opens.
--
-- Create the first account through the sign-up flow, which is also the only path
-- that produces a hash nobody else has seen.
