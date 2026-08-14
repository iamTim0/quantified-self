"""Add stable client-facing codes to sync-run status messages.

Revision ID: 015_sync_run_message_codes
Revises: 014_sync_run_event_ledger
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015_sync_run_message_codes"
down_revision: str | None = "014_sync_run_event_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add code and bounded parameters without changing existing fallback text."""
    op.execute(
        "ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS message_code VARCHAR(64);"
    )
    op.execute(
        "ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS message_params JSONB;"
    )


def downgrade() -> None:
    """Remove the optional client-facing message contract."""
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS message_params;")
    op.execute("ALTER TABLE sync_runs DROP COLUMN IF EXISTS message_code;")
