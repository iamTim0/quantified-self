"""Allow a deleted connector's display name to be reused.

Revision ID: 025_reuse_deleted_names
Revises: 024_login_attempts

Deleting a connector deliberately keeps its row and ingested data, but the old
unique constraint on ``(tenant_id, source_type, display_name)`` then blocked a
new connector from using the same name. A nullable deletion timestamp lets the
database enforce uniqueness among active connectors while retaining history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "025_reuse_deleted_names"
down_revision: str | None = "024_login_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep deleted source rows while freeing their names for new connectors."""
    op.add_column(
        "data_sources",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Older deletes were represented only by config.status. Mark those rows as
    # historical before replacing the all-rows unique constraint.
    op.execute(
        """
        UPDATE data_sources
        SET deleted_at = CURRENT_TIMESTAMP
        WHERE deleted_at IS NULL
          AND config->>'status' = 'inactive'
        """
    )
    op.execute(
        "ALTER TABLE data_sources "
        "DROP CONSTRAINT IF EXISTS uq_data_sources_tenant_type_name"
    )
    op.create_index(
        "uq_data_sources_tenant_type_name",
        "data_sources",
        ["tenant_id", "source_type", "display_name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    """Restore all-row uniqueness without deleting historical connector rows."""
    op.drop_index("uq_data_sources_tenant_type_name", table_name="data_sources")

    # The partial index permits duplicate names among deleted rows. Give those
    # rows stable, reversible-safe tombstone labels before restoring the old
    # all-row constraint; their source IDs and ingested data remain untouched.
    op.execute(
        """
        UPDATE data_sources AS deleted
        SET display_name = left(deleted.display_name, 79)
            || ' [deleted ' || deleted.id::text || ']'
        WHERE deleted.deleted_at IS NOT NULL
        """
    )
    op.create_unique_constraint(
        "uq_data_sources_tenant_type_name",
        "data_sources",
        ["tenant_id", "source_type", "display_name"],
    )
    op.drop_column("data_sources", "deleted_at")
