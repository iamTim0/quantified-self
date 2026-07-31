"""Add explorer_views table for SaaS multi-tenant backend saved views
Revision ID: 004_add_explorer_views
Revises: 003_separate_users_and_tenants
Create Date: 2026-07-31 16:24:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = '004_add_explorer_views'
down_revision: str | None = '003_separate_users_and_tenants'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Creates explorer_views table for multi-tenant backend saved views."""
    op.execute("""
        CREATE TABLE IF NOT EXISTS explorer_views (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            name VARCHAR(255) NOT NULL,
            query_config JSONB NOT NULL,
            is_shared BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_explorer_views_tenant_id ON explorer_views (tenant_id);")


def downgrade() -> None:
    """Reverts explorer_views table cleanly (Rule 7 requirement)."""
    op.execute("DROP TABLE IF EXISTS explorer_views CASCADE;")
