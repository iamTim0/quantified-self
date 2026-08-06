"""Add session, revocation, inbound API key and sync history tables

Backs four capabilities that previously had no storage at all:
  * refresh_tokens        — rotating sessions, stored as SHA-256 hashes only
  * revoked_access_tokens — the logout denylist, keyed on the access token jti
  * api_keys              — tenant-bound inbound keys for pushed data sources
  * sync_runs             — the import/audit log that adaptive windows read from

Revision ID: 006_auth_and_sync_history
Revises: 005_add_postgis_location_support
Create Date: 2026-08-06 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = '006_auth_and_sync_history'
down_revision: str | None = '005_add_postgis_location_support'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create session, revocation, API key and sync history tables."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            rotated_to_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens (token_hash);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_tenant ON refresh_tokens (tenant_id);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS revoked_access_tokens (
            jti VARCHAR(64) PRIMARY KEY,
            tenant_id UUID NOT NULL,
            user_id UUID,
            expires_at TIMESTAMPTZ NOT NULL,
            reason VARCHAR(64) NOT NULL DEFAULT 'logout',
            revoked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expiry ON revoked_access_tokens (expires_at);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_revoked_tokens_tenant ON revoked_access_tokens (tenant_id);"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            created_by_user_id UUID,
            name VARCHAR(128) NOT NULL,
            key_prefix VARCHAR(16) NOT NULL,
            key_hash VARCHAR(64) NOT NULL UNIQUE,
            source_type VARCHAR(64) NOT NULL,
            scopes JSONB NOT NULL DEFAULT '["ingest"]'::jsonb,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            expires_at TIMESTAMPTZ,
            last_used_at TIMESTAMPTZ,
            revoked_at TIMESTAMPTZ,
            rotated_from_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys (key_hash);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_tenant ON api_keys (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys (key_prefix);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS sync_runs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            source_id UUID,
            source_type VARCHAR(64) NOT NULL,
            request_id VARCHAR(128) NOT NULL,
            mode VARCHAR(16) NOT NULL DEFAULT 'smart',
            trigger VARCHAR(24) NOT NULL DEFAULT 'manual',
            window_start TIMESTAMPTZ,
            window_end TIMESTAMPTZ,
            window_reason VARCHAR(255),
            status VARCHAR(16) NOT NULL DEFAULT 'queued',
            points_received INTEGER NOT NULL DEFAULT 0,
            points_accepted INTEGER NOT NULL DEFAULT 0,
            points_duplicate INTEGER NOT NULL DEFAULT 0,
            skipped_ranges JSONB,
            message VARCHAR(512),
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at TIMESTAMPTZ
        );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_sync_runs_tenant_source_started "
        "ON sync_runs (tenant_id, source_type, started_at DESC);"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_sync_runs_request_id ON sync_runs (request_id);")

    # One connector row per (tenant, source_type). Every lookup in the codebase
    # already assumes this; without the constraint a duplicate row silently
    # shadows the configured connector.
    op.execute("""
        DELETE FROM data_sources a
        USING data_sources b
        WHERE a.ctid < b.ctid
          AND a.tenant_id = b.tenant_id
          AND a.source_type = b.source_type;
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


def downgrade() -> None:
    """Revert every object created by upgrade() (AGENTS.md rule 7)."""
    op.execute(
        "ALTER TABLE data_sources DROP CONSTRAINT IF EXISTS uq_data_sources_tenant_source_type;"
    )
    op.execute("DROP TABLE IF EXISTS sync_runs CASCADE;")
    op.execute("DROP TABLE IF EXISTS api_keys CASCADE;")
    op.execute("DROP TABLE IF EXISTS revoked_access_tokens CASCADE;")
    op.execute("DROP TABLE IF EXISTS refresh_tokens CASCADE;")
