"""Track known point totals separately from points received

Revision ID: 011_sync_run_expected_points
Revises: 010_field_reports
Create Date: 2026-08-09 00:00:00.000000

Webhook and archive importers sometimes know the number of events before they
publish them. `points_received` was previously overloaded for that estimate, which
made a run appear complete before its events reached Core. Keep the estimate in its
own nullable column so progress can distinguish a known total from an open-ended
provider push.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "011_sync_run_expected_points"
down_revision: str | None = "010_field_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the optional expected point count to import runs."""
    op.execute(
        "ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS points_expected INTEGER;"
    )


def downgrade() -> None:
    """Remove the optional expected point count."""
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS points_expected;")
