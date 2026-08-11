"""Keep unknown metric values until a tenant resolves their meaning.

Revision ID: 012_metric_mapping_quarantine
Revises: 011_sync_run_expected_points
"""

from collections.abc import Sequence

from alembic import op

revision: str = "012_metric_mapping_quarantine"
down_revision: str | None = "011_sync_run_expected_points"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tenant-scoped quarantine, mapping, and refusal audit tables."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS metric_mapping_rules (
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
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quarantined_data_points (
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
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quarantine_refusals (
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
        """
    )
    op.execute(
        "ALTER TABLE metric_mapping_rules ADD COLUMN IF NOT EXISTS retention_days INTEGER;"
    )
    op.execute(
        "ALTER TABLE quarantined_data_points ADD COLUMN IF NOT EXISTS idempotency_source_id VARCHAR(512);"
    )
    op.execute(
        "UPDATE quarantined_data_points SET idempotency_source_id = source_id "
        "WHERE idempotency_source_id IS NULL;"
    )
    op.execute(
        "ALTER TABLE quarantined_data_points ALTER COLUMN idempotency_source_id SET NOT NULL;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_quarantine_active_source_name "
        "ON quarantined_data_points (tenant_id, source_id, raw_metric_type) "
        "WHERE status = 'active';"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mapping_rules_tenant_source "
        "ON metric_mapping_rules (tenant_id, source_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_quarantine_refusals_tenant_source "
        "ON quarantine_refusals (tenant_id, source_id);"
    )


def downgrade() -> None:
    """Drop the Phase 8 tables in dependency-safe order."""
    op.execute("DROP TABLE IF EXISTS quarantine_refusals CASCADE;")
    op.execute("DROP TABLE IF EXISTS quarantined_data_points CASCADE;")
    op.execute("DROP TABLE IF EXISTS metric_mapping_rules CASCADE;")
