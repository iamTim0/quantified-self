"""Record which provider fields an importer read, and which it did not

Revision ID: 010_field_reports
Revises: 009_multi_instance
Create Date: 2026-08-09 00:00:00.000000

Four families of Apple Health data were being dropped silently — heart rate, blood
pressure, workout energy and workout distance all arrive under names the transformer
did not read. Nothing failed, so nothing said so, and the only way anyone found out
was by holding the provider's documentation against the code by hand.

This table is what lets the software ask the question instead. It stores the *shape*
of what arrives and nothing else: a path, the kind of value that sat there, and how
often it was seen. No payload is kept — that would be a second copy of the most
sensitive data in the system, with its own retention question, and would make the
account deletion incomplete unless it hunted that copy down too.

Rolling rather than append-only: one row per (tenant, connector, path), upserted on
every import. So the table grows with the *provider's schema*, not with the data, and
needs no retention policy of its own. It cascades from both `tenants` and
`data_sources`, so deleting either takes it along.
"""
from collections.abc import Sequence

from alembic import op

revision: str = '010_field_reports'
down_revision: str | None = '009_multi_instance'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ingest_field_reports (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_id UUID NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            source_type VARCHAR(64) NOT NULL,
            field_path VARCHAR(512) NOT NULL,
            value_kind VARCHAR(16) NOT NULL,
            metric_type VARCHAR(128),
            occurrences INTEGER NOT NULL DEFAULT 0,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_sync_run_id UUID,
            CONSTRAINT uq_field_reports_tenant_source_path
                UNIQUE (tenant_id, source_id, field_path)
        );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_field_reports_tenant_source "
        "ON ingest_field_reports (tenant_id, source_id);"
    )
    # The list the dashboard actually shows: fields seen and never stored.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_field_reports_unmapped "
        "ON ingest_field_reports (tenant_id, source_id) WHERE metric_type IS NULL;"
    )


def downgrade() -> None:
    """Drop the table.

    Lossy only in the sense that the observations are gone; they are rebuilt from
    scratch by the next import of each connector, because every import reports its
    whole shape rather than a delta.
    """
    op.execute("DROP TABLE IF EXISTS ingest_field_reports CASCADE;")
