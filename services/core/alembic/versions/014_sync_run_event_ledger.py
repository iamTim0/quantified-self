"""Make Core sync-run progress idempotent across broker redeliveries.

Revision ID: 014_sync_run_event_ledger
Revises: 013_sync_run_core_processing
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014_sync_run_event_ledger"
down_revision: str | None = "013_sync_run_core_processing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the tenant-scoped once-only progress ledger."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_run_events (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            sync_run_id UUID NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
            event_key VARCHAR(128) NOT NULL,
            counted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_sync_run_events_tenant_run_key
                UNIQUE (tenant_id, sync_run_id, event_key)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_sync_run_events_tenant_run
        ON sync_run_events (tenant_id, sync_run_id);
        """
    )


def downgrade() -> None:
    """Drop the progress ledger and its index."""
    op.execute("DROP INDEX IF EXISTS idx_sync_run_events_tenant_run;")
    op.execute("DROP TABLE IF EXISTS sync_run_events CASCADE;")
