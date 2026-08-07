"""Add configurable OIDC providers, in-flight auth requests and federated identities

Revision ID: 007_add_oidc
Revises: 006_auth_and_sync_history
Create Date: 2026-08-07 00:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = '007_add_oidc'
down_revision: str | None = '006_auth_and_sync_history'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create OIDC provider configuration, auth-request and identity-link tables."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS oidc_providers (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            slug VARCHAR(64) NOT NULL UNIQUE,
            display_name VARCHAR(128) NOT NULL,
            issuer VARCHAR(512) NOT NULL,
            client_id VARCHAR(512) NOT NULL,
            encrypted_client_secret VARCHAR(2048),
            scopes VARCHAR(512) NOT NULL DEFAULT 'openid email profile',
            redirect_uri VARCHAR(512) NOT NULL,
            claims_mapping JSONB NOT NULL DEFAULT '{}'::jsonb,
            enabled BOOLEAN NOT NULL DEFAULT false,
            allow_signup BOOLEAN NOT NULL DEFAULT false,
            require_verified_email BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_oidc_providers_slug ON oidc_providers (slug);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS oidc_auth_requests (
            state VARCHAR(128) PRIMARY KEY,
            provider_slug VARCHAR(64) NOT NULL,
            nonce VARCHAR(128) NOT NULL,
            code_verifier VARCHAR(256) NOT NULL,
            redirect_uri VARCHAR(512) NOT NULL,
            link_user_id UUID,
            consumed_at TIMESTAMPTZ,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_oidc_auth_requests_expiry ON oidc_auth_requests (expires_at);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_oidc_auth_requests_provider ON oidc_auth_requests (provider_slug);"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_identities (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL,
            provider_slug VARCHAR(64) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            last_login_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_identities_provider_subject UNIQUE (provider_slug, subject)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities (user_id);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_identities_tenant ON user_identities (tenant_id);"
    )


def downgrade() -> None:
    """Revert every object created by upgrade() (AGENTS.md rule 7)."""
    op.execute("DROP TABLE IF EXISTS user_identities CASCADE;")
    op.execute("DROP TABLE IF EXISTS oidc_auth_requests CASCADE;")
    op.execute("DROP TABLE IF EXISTS oidc_providers CASCADE;")
