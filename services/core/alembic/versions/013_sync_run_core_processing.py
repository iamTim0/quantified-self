"""Track events processed by Core before an import run is complete.

Revision ID: 013_sync_run_core_processing
Revises: 012_metric_mapping_quarantine
"""

from collections.abc import Sequence

from alembic import op

revision: str = "013_sync_run_core_processing"
down_revision: str | None = "012_metric_mapping_quarantine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the Core-side processing counter used to close drained runs."""
    op.execute(
        "ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS points_processed INTEGER NOT NULL DEFAULT 0;"
    )


def downgrade() -> None:
    """Remove the Core-side processing counter."""
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS points_processed;")
