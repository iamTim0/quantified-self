"""Session-keyed reads, a second resolution tier, and retention that can say never.

Revision ID: 023_workout_sessions
Revises: 022_day_report_kind

Three changes, all in service of reading one workout back out of flat points:

* A partial index on `metadata->>'session_id'`, which is what the workout list and
  the workout detail filter on. Partial because most rows never carry one — a
  location fix from Dawarich, a meal, a night's sleep — and an index over the whole
  hypertable to serve the fraction that do is a cost paid on every write.
* `metric_ingest_policies.resolution` gains `'second'`. Heart rate is stored per
  second now, because a minute mean of an interval session is a flat line.
* `metric_ingest_policies.raw_retention_days` becomes nullable, where NULL means
  *never purge*. It belongs to the metrics whose fine-grained form is the data: a
  day rollup of `strength_set_weight` is the heaviest thing lifted that day, and a
  `location_point` rollup is a count, so purging either deletes the measurement
  rather than keeping its aggregate.
"""

from collections.abc import Sequence

from alembic import op

# 20 characters; `alembic_version.version_num` is VARCHAR(32).
revision: str = "023_workout_sessions"
down_revision: str | None = "022_day_report_kind"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_data_points_tenant_session
            ON data_points (tenant_id, (metadata->>'session_id'), timestamp)
            WHERE metadata ? 'session_id';
        """
    )

    op.execute(
        "ALTER TABLE metric_ingest_policies "
        "DROP CONSTRAINT IF EXISTS ck_metric_ingest_policies_resolution;"
    )
    op.execute(
        """
        ALTER TABLE metric_ingest_policies ADD CONSTRAINT ck_metric_ingest_policies_resolution
            CHECK (resolution IN ('raw', 'second', 'minute', 'hour', 'day'));
        """
    )

    op.execute(
        "ALTER TABLE metric_ingest_policies ALTER COLUMN raw_retention_days DROP NOT NULL;"
    )
    op.execute(
        "ALTER TABLE metric_ingest_policies "
        "DROP CONSTRAINT IF EXISTS ck_metric_ingest_policies_retention;"
    )
    op.execute(
        """
        ALTER TABLE metric_ingest_policies ADD CONSTRAINT ck_metric_ingest_policies_retention
            CHECK (
                raw_retention_days IS NULL
                OR (raw_retention_days >= 0 AND raw_retention_days <= 3650)
            );
        """
    )


def downgrade() -> None:
    """Functional, and lossy in two places that are named rather than hidden.

    A `NULL` retention becomes 90 days again and a `'second'` policy becomes
    `'minute'`, because the old constraints reject both and a downgrade that
    leaves rows the schema forbids is one that cannot be re-applied. Neither
    deletes data: they are settings that describe what *future* imports do, and
    points already stored keep the resolution they were stored at.
    """
    op.execute(
        "UPDATE metric_ingest_policies SET raw_retention_days = 90 "
        "WHERE raw_retention_days IS NULL;"
    )
    op.execute(
        "ALTER TABLE metric_ingest_policies "
        "DROP CONSTRAINT IF EXISTS ck_metric_ingest_policies_retention;"
    )
    op.execute(
        """
        ALTER TABLE metric_ingest_policies ADD CONSTRAINT ck_metric_ingest_policies_retention
            CHECK (raw_retention_days >= 0 AND raw_retention_days <= 3650);
        """
    )
    op.execute(
        "ALTER TABLE metric_ingest_policies ALTER COLUMN raw_retention_days SET NOT NULL;"
    )

    op.execute("UPDATE metric_ingest_policies SET resolution = 'minute' WHERE resolution = 'second';")
    op.execute(
        "ALTER TABLE metric_ingest_policies "
        "DROP CONSTRAINT IF EXISTS ck_metric_ingest_policies_resolution;"
    )
    op.execute(
        """
        ALTER TABLE metric_ingest_policies ADD CONSTRAINT ck_metric_ingest_policies_resolution
            CHECK (resolution IN ('raw', 'minute', 'hour', 'day'));
        """
    )

    op.execute("DROP INDEX IF EXISTS idx_data_points_tenant_session;")
