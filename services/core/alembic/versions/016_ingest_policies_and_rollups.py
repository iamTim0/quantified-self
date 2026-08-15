"""Add tenant ingest policies and incrementally maintained metric rollups.

Revision ID: 016_ingest_policies_and_rollups
Revises: 015_sync_run_message_codes
"""

from collections.abc import Sequence

from alembic import op

revision: str = "016_ingest_policies_and_rollups"
down_revision: str | None = "015_sync_run_message_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tenant-scoped resolution overrides and rollup storage."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS metric_ingest_policies (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            metric_type VARCHAR(128) NOT NULL,
            resolution VARCHAR(16) NOT NULL,
            raw_retention_days INTEGER NOT NULL DEFAULT 90,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_metric_ingest_policies_tenant_metric
                UNIQUE (tenant_id, metric_type),
            CONSTRAINT ck_metric_ingest_policies_resolution
                CHECK (resolution IN ('raw', 'minute', 'hour', 'day')),
            CONSTRAINT ck_metric_ingest_policies_retention
                CHECK (raw_retention_days >= 0 AND raw_retention_days <= 3650)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_metric_ingest_policies_tenant
            ON metric_ingest_policies (tenant_id);
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS metric_rollups (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            metric_type VARCHAR(128) NOT NULL,
            resolution VARCHAR(16) NOT NULL,
            bucket_start TIMESTAMPTZ NOT NULL,
            value DOUBLE PRECISION,
            sample_count INTEGER NOT NULL DEFAULT 0,
            sum_value DOUBLE PRECISION,
            min_value DOUBLE PRECISION,
            max_value DOUBLE PRECISION,
            first_value DOUBLE PRECISION,
            last_value DOUBLE PRECISION,
            first_timestamp TIMESTAMPTZ,
            last_timestamp TIMESTAMPTZ,
            metadata JSONB,
            is_provider_total BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_metric_rollups_tenant_source_metric_resolution_bucket
                UNIQUE (tenant_id, source_id, metric_type, resolution, bucket_start),
            CONSTRAINT ck_metric_rollups_resolution
                CHECK (resolution IN ('minute', 'hour', 'day'))
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_metric_rollups_tenant_resolution_time
            ON metric_rollups (tenant_id, resolution, bucket_start DESC);
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_metric_rollups_tenant_metric_time
            ON metric_rollups (tenant_id, metric_type, bucket_start DESC);
        """
    )


def downgrade() -> None:
    """Drop rollups and policies while leaving canonical data points untouched."""
    op.execute("DROP INDEX IF EXISTS idx_metric_rollups_tenant_metric_time;")
    op.execute("DROP INDEX IF EXISTS idx_metric_rollups_tenant_resolution_time;")
    op.execute("DROP TABLE IF EXISTS metric_rollups;")
    op.execute("DROP INDEX IF EXISTS idx_metric_ingest_policies_tenant;")
    op.execute("DROP TABLE IF EXISTS metric_ingest_policies;")
