"""Add precomputed report runs and per-metric primary source preferences.

Revision ID: 020_report_runs_and_sources
Revises: 019_tenant_source_fks
"""

from collections.abc import Sequence

from alembic import op

# 27 characters. `alembic_version.version_num` is varchar(32), so a longer id
# creates its tables and then fails on the version bump — a migration that
# half-applies and reports failure.
revision: str = "020_report_runs_and_sources"
down_revision: str | None = "019_tenant_source_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the report ledger and the metric source preference table."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_runs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            kind VARCHAR(32) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'queued',
            trigger VARCHAR(24) NOT NULL DEFAULT 'scheduled',
            request_id VARCHAR(128) NOT NULL,
            -- The newest completed import this report saw. Comparing it with the
            -- tenant's newest finished sync is what makes a report "stale" without
            -- recomputing it to find out.
            covers_data_through TIMESTAMPTZ,
            payload JSONB,
            params JSONB,
            message VARCHAR(512),
            message_code VARCHAR(64),
            message_params JSONB,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ,
            CONSTRAINT uq_report_runs_tenant_id_id UNIQUE (tenant_id, id),
            CONSTRAINT ck_report_runs_kind
                CHECK (kind IN ('gaps', 'conflicts', 'insights')),
            CONSTRAINT ck_report_runs_status
                CHECK (status IN ('queued', 'running', 'success', 'error')),
            CONSTRAINT ck_report_runs_trigger
                CHECK (trigger IN ('scheduled', 'manual'))
        );
        """
    )
    # The read path is always "newest successful run of this kind for this
    # tenant", so that is the index. Partial on success because a failed or
    # in-flight run is never what a reader is shown.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_report_runs_tenant_kind_finished
            ON report_runs (tenant_id, kind, finished_at DESC)
            WHERE status = 'success';
        """
    )
    # The scheduler's due-check and the in-flight guard both ask for runs that
    # have not finished, across every tenant.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_report_runs_in_flight
            ON report_runs (tenant_id, kind, started_at DESC)
            WHERE status IN ('queued', 'running');
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS metric_source_preferences (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            metric_type VARCHAR(128) NOT NULL,
            -- Which connector instance answers for this metric when several
            -- report it. NULL is not a row: absence means "decide by coverage".
            primary_source_id UUID NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_metric_source_preferences_tenant_metric
                UNIQUE (tenant_id, metric_type),
            CONSTRAINT fk_metric_source_preferences_tenant_source
                FOREIGN KEY (tenant_id, primary_source_id)
                REFERENCES data_sources (tenant_id, id) ON DELETE CASCADE
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_metric_source_preferences_tenant
            ON metric_source_preferences (tenant_id);
        """
    )


def downgrade() -> None:
    """Drop both tables. Neither holds anything that cannot be recomputed."""
    op.execute("DROP INDEX IF EXISTS idx_metric_source_preferences_tenant;")
    op.execute("DROP TABLE IF EXISTS metric_source_preferences;")
    op.execute("DROP INDEX IF EXISTS idx_report_runs_in_flight;")
    op.execute("DROP INDEX IF EXISTS idx_report_runs_tenant_kind_finished;")
    op.execute("DROP TABLE IF EXISTS report_runs;")
