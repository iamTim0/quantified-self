"""Add provider coverage and rejection counters to sync runs.

Revision ID: 017_sync_run_coverage
Revises: 016_ingest_policies_and_rollups
"""

from collections.abc import Sequence

from alembic import op

revision: str = "017_sync_run_coverage"
down_revision: str | None = "016_ingest_policies_and_rollups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add bounded run-level completeness information."""
    op.execute("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS points_rejected INTEGER NOT NULL DEFAULT 0;")
    op.execute("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS unsupported_fields INTEGER NOT NULL DEFAULT 0;")
    op.execute("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS provider_window_start TIMESTAMPTZ;")
    op.execute("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS provider_window_end TIMESTAMPTZ;")
    op.execute("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS provider_exported_at TIMESTAMPTZ;")
    op.execute("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS backlog_at_start INTEGER;")
    op.execute("ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS backlog_at_end INTEGER;")


def downgrade() -> None:
    """Remove optional coverage fields without touching the import ledger."""
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS backlog_at_end;")
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS backlog_at_start;")
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS provider_exported_at;")
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS provider_window_end;")
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS provider_window_start;")
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS unsupported_fields;")
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS points_rejected;")
