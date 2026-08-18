"""Record whether a newly supported field's missed history has been re-imported.

Revision ID: 027_field_history_backfill
Revises: 026_field_support_transitions
Create Date: 2026-08-17

026 recorded *that* a field stopped being unsupported. It did not recover anything:
the readings that arrived between `first_seen_at` and `supported_since` were never
stored, and support arriving today does nothing for them. The Data Quality Center
reported the gap and left the user to force an import over it by hand.

`history_backfilled_at` is what lets that happen automatically without happening
twice. It is stamped only once a force run has actually been queued for the span,
so a connector that was busy at sweep time stays pending instead of being recorded
as recovered — the difference between "it did not run" and "it ran and found
nothing".

No data backfill here, deliberately. Every row this migration meets is either
supported since it was first seen (026 set those two timestamps equal, so there is
no gap) or not yet supported at all. A pending recovery cannot exist before the
column that records one.
"""

import sqlalchemy as sa
from alembic import op

revision = "027_field_history_backfill"
down_revision = "026_field_support_transitions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingest_field_reports",
        sa.Column("history_backfilled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The sweep's index. Partial on both halves of what it looks for, because the
    # rows that need recovering are a vanishing fraction of the table and are gone
    # from the index the moment they are stamped — so a query that normally returns
    # nothing costs nothing, which is what makes a 15-minute tick reasonable.
    op.create_index(
        "idx_field_reports_pending_backfill",
        "ingest_field_reports",
        ["tenant_id", "source_id"],
        postgresql_where=sa.text(
            "supported_since IS NOT NULL AND history_backfilled_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("idx_field_reports_pending_backfill", table_name="ingest_field_reports")
    op.drop_column("ingest_field_reports", "history_backfilled_at")
