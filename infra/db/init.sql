-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create tenants table
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create data_sources table
CREATE TABLE data_sources (
    id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    source_type TEXT NOT NULL, -- e.g., 'oura', 'whoop'
    config JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
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

-- Create tenant_shares table for cross-tenant data sharing
CREATE TABLE tenant_shares (
    id UUID PRIMARY KEY,
    grantor_tenant_id UUID REFERENCES tenants(id),
    grantee_tenant_id UUID REFERENCES tenants(id),
    scope TEXT NOT NULL, -- e.g., 'read_all', 'read_metric:sleep_score'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (grantor_tenant_id, grantee_tenant_id, scope)
);
