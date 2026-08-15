"""Make user email uniqueness case-insensitive.

Revision ID: 018_case_insensitive_user_email
Revises: 017_sync_run_coverage
"""

from collections.abc import Sequence

from alembic import op

revision: str = "018_case_insensitive_user_email"
down_revision: str | None = "017_sync_run_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Prevent two accounts from differing only by email-letter case."""
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_case_insensitive
            ON users (LOWER(email));
        """
    )


def downgrade() -> None:
    """Remove the expression index while preserving the existing email column."""
    op.execute("DROP INDEX IF EXISTS uq_users_email_case_insensitive;")
