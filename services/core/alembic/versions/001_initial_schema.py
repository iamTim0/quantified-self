"""Initial database schema with TimescaleDB & pgvector support.

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-07-25 19:40:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = '001_initial_schema'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    # 1. Extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb;")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")

    # 2. Tenants table
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # 3. Data Sources table
    op.execute("""
        CREATE TABLE IF NOT EXISTS data_sources (
            id UUID PRIMARY KEY,
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            source_type TEXT NOT NULL,
            config JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)

    # 4. Data Points table & hypertable
    op.execute("""
        CREATE TABLE IF NOT EXISTS data_points (
            id UUID DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            source_id UUID NOT NULL REFERENCES data_sources(id),
            metric_type TEXT NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            value DOUBLE PRECISION,
            metadata JSONB DEFAULT '{}',
            embedding vector(1536),
            idempotency_key TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (id, timestamp),
            UNIQUE (tenant_id, idempotency_key, timestamp)
        );
    """)
    op.execute("SELECT create_hypertable('data_points', 'timestamp', if_not_exists => TRUE);")

    # Indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_data_points_tenant_metric_time ON data_points (tenant_id, metric_type, timestamp DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_data_points_tenant_source_time ON data_points (tenant_id, source_id, timestamp DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_data_points_metadata ON data_points USING GIN (metadata);")

    # 5. Tenant Shares table
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_shares (
            id UUID PRIMARY KEY,
            grantor_tenant_id UUID REFERENCES tenants(id),
            grantee_tenant_id UUID REFERENCES tenants(id),
            scope TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE (grantor_tenant_id, grantee_tenant_id, scope)
        );
    """)

def downgrade() -> None:
    """EXPLICIT ROLLBACK: Reverts upgrade() cleanly in reverse order."""
    op.execute("DROP TABLE IF EXISTS tenant_shares CASCADE;")
    op.execute("DROP TABLE IF EXISTS data_points CASCADE;")
    op.execute("DROP TABLE IF EXISTS data_sources CASCADE;")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE;")
