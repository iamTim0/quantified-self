"""Allow several connectors of the same type per tenant

Revision ID: 009_multi_instance
Revises: 008_session_cutoff
Create Date: 2026-08-09 00:00:00.000000

`UNIQUE (tenant_id, source_type)` from 006 made a second calendar impossible, and
a calendar is exactly the thing people have more than one of — work, family, the
one the gym publishes. The same is true of weather locations and of Home Assistant
instances.

Nothing about the stored data has to change. `source_id` is already the second
component of every ``idempotency_key`` (``shared_schemas.events.idempotency_key``),
so a second instance gets its own key space by construction; re-keying existing
points would instead double the history, which that function's docstring warns
about at length.

Two columns are added because dropping the constraint alone would leave the system
unable to say *which* connector anything belongs to:

* ``data_sources.display_name`` — what the user calls this instance. Required:
  "which of my three calendars is this?" has no answer the system could invent.
* ``api_keys.source_id`` — a push key used to name only a *type*. With two Apple
  Health connectors that no longer identifies where an inbound reading belongs,
  and that decision picks the ``source_id`` every idempotency key is built from.

Both are backfilled from what exists before being made NOT NULL, so the migration
is safe to run against a populated database even though this one is not.
"""
from collections.abc import Sequence

from alembic import op

revision: str = '009_multi_instance'
down_revision: str | None = '008_session_cutoff'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── data_sources.display_name ────────────────────────────────────────────
    op.execute("ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS display_name VARCHAR(128);")
    # Existing rows predate the concept, and there is exactly one per type, so the
    # type itself is an honest name for it: "calendar", "weather".
    op.execute("UPDATE data_sources SET display_name = source_type WHERE display_name IS NULL;")
    op.execute("ALTER TABLE data_sources ALTER COLUMN display_name SET NOT NULL;")

    # ── the constraint this migration exists to remove ───────────────────────
    op.execute(
        "ALTER TABLE data_sources DROP CONSTRAINT IF EXISTS uq_data_sources_tenant_source_type;"
    )
    # Two instances of a type are the point; two with the same name are not,
    # because the list a user picks from would then show two identical rows.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_data_sources_tenant_type_name'
            ) THEN
                ALTER TABLE data_sources
                    ADD CONSTRAINT uq_data_sources_tenant_type_name
                    UNIQUE (tenant_id, source_type, display_name);
            END IF;
        END $$;
    """)

    # ── api_keys.source_id ───────────────────────────────────────────────────
    op.execute("ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS source_id UUID;")
    # Exactly one connector of each type existed until now, so the key's type
    # resolves to precisely one row and the backfill is unambiguous.
    op.execute("""
        UPDATE api_keys k
        SET source_id = d.id
        FROM data_sources d
        WHERE k.source_id IS NULL
          AND d.tenant_id = k.tenant_id
          AND d.source_type = k.source_type;
    """)
    # A key whose connector no longer exists cannot be honoured either way: it
    # would resolve to no source_id and every push under it would be rejected.
    op.execute("DELETE FROM api_keys WHERE source_id IS NULL;")
    op.execute("ALTER TABLE api_keys ALTER COLUMN source_id SET NOT NULL;")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_api_keys_source_id'
            ) THEN
                ALTER TABLE api_keys
                    ADD CONSTRAINT fk_api_keys_source_id
                    FOREIGN KEY (source_id) REFERENCES data_sources (id) ON DELETE CASCADE;
            END IF;
        END $$;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_source_id ON api_keys (source_id);")

    # ── sync_runs, queried per instance from here on ─────────────────────────
    # `source_id` has been written since 006 but never read; the scheduler and the
    # adaptive-window query both keyed on `source_type`, so one calendar would
    # block the other for up to six hours and advance its resume point.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_runs_tenant_source_id_started "
        "ON sync_runs (tenant_id, source_id, started_at DESC);"
    )


def downgrade() -> None:
    """Restore one connector per (tenant, source_type).

    Lossy by nature, and deliberately explicit about it: if a tenant has created a
    second calendar since the upgrade, the old constraint cannot be recreated while
    both rows exist. The duplicates are deleted newest-first, keeping the oldest
    instance of each type — the one that existed before this migration, and the one
    whose data any pre-009 code would have been reading.

    Their data points are *not* deleted. They keep referring to a connector row
    that is gone, which is the same state a soft-deleted connector already leaves
    behind, and is recoverable; deleting somebody's history to reverse a schema
    change is not.
    """
    op.execute("DROP INDEX IF EXISTS idx_sync_runs_tenant_source_id_started;")

    op.execute("ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS fk_api_keys_source_id;")
    op.execute("DROP INDEX IF EXISTS idx_api_keys_source_id;")
    op.execute("ALTER TABLE api_keys DROP COLUMN IF EXISTS source_id;")

    op.execute(
        "ALTER TABLE data_sources DROP CONSTRAINT IF EXISTS uq_data_sources_tenant_type_name;"
    )
    op.execute("""
        DELETE FROM data_sources a
        USING data_sources b
        WHERE a.tenant_id = b.tenant_id
          AND a.source_type = b.source_type
          AND (a.created_at, a.id) > (b.created_at, b.id);
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_data_sources_tenant_source_type'
            ) THEN
                ALTER TABLE data_sources
                    ADD CONSTRAINT uq_data_sources_tenant_source_type
                    UNIQUE (tenant_id, source_type);
            END IF;
        END $$;
    """)
    op.execute("ALTER TABLE data_sources DROP COLUMN IF EXISTS display_name;")
