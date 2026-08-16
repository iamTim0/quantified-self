"""Allow `day` as a report kind, so the daily story is precomputed too.

Revision ID: 022_day_report_kind
Revises: 020_report_runs_and_sources
"""

from collections.abc import Sequence

from alembic import op

# 19 characters; `alembic_version.version_num` is VARCHAR(32).
revision: str = "022_day_report_kind"
down_revision: str | None = "020_report_runs_and_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Widen the kind check. The daily story joins the other derivations."""
    op.execute("ALTER TABLE report_runs DROP CONSTRAINT IF EXISTS ck_report_runs_kind;")
    op.execute(
        """
        ALTER TABLE report_runs ADD CONSTRAINT ck_report_runs_kind
            CHECK (kind IN ('gaps', 'conflicts', 'insights', 'day'));
        """
    )


def downgrade() -> None:
    """Narrow it again, dropping any stored day reports first.

    They have to go: the old constraint would reject them, and a downgrade that
    leaves rows the schema forbids is one that cannot be re-applied. Nothing is
    lost — a report is derived from data that is still there.
    """
    op.execute("DELETE FROM report_runs WHERE kind = 'day';")
    op.execute("ALTER TABLE report_runs DROP CONSTRAINT IF EXISTS ck_report_runs_kind;")
    op.execute(
        """
        ALTER TABLE report_runs ADD CONSTRAINT ck_report_runs_kind
            CHECK (kind IN ('gaps', 'conflicts', 'insights'));
        """
    )
