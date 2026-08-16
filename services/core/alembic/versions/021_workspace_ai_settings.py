"""Add per-workspace AI settings and day-summary embeddings.

Revision ID: 021_workspace_ai
Revises: 020_report_runs_and_sources
"""

from collections.abc import Sequence

from alembic import op

# 15 characters. `alembic_version.version_num` is VARCHAR(32); see the structural
# test in tools/tests/test_service_boundaries.py.
revision: str = "021_workspace_ai"
down_revision: str | None = "020_report_runs_and_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the opt-in AI configuration and the day-summary vector store."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_ai_settings (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
            -- Off unless somebody turns it on. Health data leaving the instance
            -- for a third-party model is a decision an operator makes, not a
            -- default they discover afterwards.
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            provider VARCHAR(16) NOT NULL DEFAULT 'codex',
            -- LiteLLM only. Fernet-encrypted at rest exactly like a connector
            -- credential (rule 12); never returned in plaintext by any endpoint.
            encrypted_api_key TEXT,
            base_url VARCHAR(255),
            chat_model VARCHAR(128),
            embedding_model VARCHAR(128) NOT NULL DEFAULT 'text-embedding-3-small',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_workspace_ai_provider
                CHECK (provider IN ('codex', 'litellm')),
            -- A LiteLLM workspace without an endpoint is a configuration that
            -- cannot work; refusing it here beats failing on the first run.
            CONSTRAINT ck_workspace_ai_litellm_has_endpoint
                CHECK (
                    provider <> 'litellm'
                    OR NOT enabled
                    OR (base_url IS NOT NULL AND encrypted_api_key IS NOT NULL)
                )
        );
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS metric_day_embeddings (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            -- One vector per day and metric category, not per data point. A
            -- single step count carries no meaning a similarity search could
            -- use, and six million of them would be millions of API calls and
            -- gigabytes of vectors to answer a question nobody asked.
            day DATE NOT NULL,
            category VARCHAR(32) NOT NULL,
            -- The sentence that was embedded, kept so a reader can see what the
            -- model was actually given. Derived from stored rollups; it holds no
            -- provider payload.
            summary TEXT NOT NULL,
            embedding VECTOR(1536),
            model VARCHAR(128) NOT NULL,
            -- Lets a model change invalidate its own vectors without a migration.
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_metric_day_embeddings_tenant_day_category
                UNIQUE (tenant_id, day, category)
        );
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_metric_day_embeddings_tenant_day
            ON metric_day_embeddings (tenant_id, day DESC);
        """
    )
    # IVFFlat needs rows before it can be built usefully, and a personal
    # workspace has thousands of vectors rather than millions — an exact scan
    # over a few thousand is faster than an approximate index and never wrong.
    # The index is deliberately omitted until volume justifies it.


def downgrade() -> None:
    """Drop both tables. Vectors are recomputable; settings are re-entered."""
    op.execute("DROP INDEX IF EXISTS idx_metric_day_embeddings_tenant_day;")
    op.execute("DROP TABLE IF EXISTS metric_day_embeddings;")
    op.execute("DROP TABLE IF EXISTS workspace_ai_settings;")
