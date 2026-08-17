"""Record when a provider field stopped being unsupported.

Revision ID: 026_field_support_transitions
Revises: 025_reuse_deleted_names
Create Date: 2026-08-17

`ingest_field_reports.metric_type IS NULL` has always meant "this arrives and we do
not store it". What was missing is the *transition*: a field that becomes supported
looks, afterwards, exactly like a field that was always supported. So the one
question a user actually has — "the thing I reported as missing, does it work now?"
— had no answer, and the historical data for that field stayed missing with nothing
recording that it could now be recovered.

`supported_since` is that transition. It is set once, by the upsert, at the moment a
row's `metric_type` goes from NULL to a name, and never cleared afterwards.
"""

import sqlalchemy as sa
from alembic import op

revision = "026_field_support_transitions"
down_revision = "025_reuse_deleted_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingest_field_reports",
        sa.Column("supported_since", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing supported rows are backfilled as "supported before this migration"
    # rather than left NULL. NULL would otherwise mean two different things at once
    # — never supported, and supported so long ago nobody recorded it — and the
    # newly-supported view would read the whole existing catalogue as brand new the
    # first time anybody opened it.
    op.execute(
        """
        UPDATE ingest_field_reports
        SET supported_since = first_seen_at
        WHERE metric_type IS NOT NULL
        """
    )
    # The newly-supported view's own index. Partial, like the unmapped one beside
    # it: the interesting rows are a small minority of the table forever.
    op.create_index(
        "idx_field_reports_newly_supported",
        "ingest_field_reports",
        ["tenant_id", "supported_since"],
        postgresql_where=sa.text("supported_since IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_field_reports_newly_supported", table_name="ingest_field_reports")
    op.drop_column("ingest_field_reports", "supported_since")
