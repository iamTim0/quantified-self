"""Enforce tenant/source consistency at the database boundary.

The application already scopes source queries by tenant. These constraints add a
second line of defense so a future query or forged event cannot pair one tenant's
identifier with another tenant's connector.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "019_tenant_source_fks"
down_revision: str | None = "018_case_insensitive_user_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCE_CONSTRAINTS = {
    "data_points": "fk_data_points_tenant_source",
    "metric_rollups": "fk_metric_rollups_tenant_source",
    "ingest_field_reports": "fk_field_reports_tenant_source",
    "quarantined_data_points": "fk_quarantine_tenant_source",
    "metric_mapping_rules": "fk_metric_mapping_tenant_source",
    "quarantine_refusals": "fk_quarantine_refusal_tenant_source",
}


def _add_constraint_if_missing(table: str, name: str, ddl: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{name}'
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} {ddl} NOT VALID;
            END IF;
        END $$;
        """
    )


def _add_unique_if_missing(table: str, name: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = '{name}'
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE (tenant_id, id);
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    """Add tenant-aware uniqueness and foreign keys.

    Existing installations may contain rows created before tenant/source checks
    existed. ``NOT VALID`` keeps deployment available while enforcing the rule for
    all new writes; operators can validate after repairing any reported legacy rows.
    """
    _add_unique_if_missing("data_sources", "uq_data_sources_tenant_id_id")
    _add_unique_if_missing("sync_runs", "uq_sync_runs_tenant_id_id")

    for table, name in _SOURCE_CONSTRAINTS.items():
        _add_constraint_if_missing(
            table,
            name,
            "FOREIGN KEY (tenant_id, source_id) REFERENCES data_sources (tenant_id, id)",
        )

    _add_constraint_if_missing(
        "sync_run_events",
        "fk_sync_run_events_tenant_run",
        "FOREIGN KEY (tenant_id, sync_run_id) REFERENCES sync_runs (tenant_id, id)",
    )


def downgrade() -> None:
    """Remove tenant-aware constraints while preserving existing data."""
    op.execute(
        "ALTER TABLE sync_run_events DROP CONSTRAINT IF EXISTS fk_sync_run_events_tenant_run"
    )
    for table, name in _SOURCE_CONSTRAINTS.items():
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute("ALTER TABLE sync_runs DROP CONSTRAINT IF EXISTS uq_sync_runs_tenant_id_id")
    op.execute("ALTER TABLE data_sources DROP CONSTRAINT IF EXISTS uq_data_sources_tenant_id_id")
