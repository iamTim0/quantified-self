"""Separate users and tenants table
Revision ID: 003_separate_users_and_tenants
Revises: 002_add_auth_fields
Create Date: 2026-07-26 21:05:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = '003_separate_users_and_tenants'
down_revision: str | None = '002_add_auth_fields'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create users table
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'owner',
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);")

    # 2. Migrate existing tenant emails/passwords into users table if present
    op.execute("""
        INSERT INTO users (id, tenant_id, email, password_hash, name, role, created_at)
        SELECT uuid_generate_v4(), id, email, password_hash, name, 'owner', created_at
        FROM tenants
        WHERE email IS NOT NULL AND password_hash IS NOT NULL
        ON CONFLICT (email) DO NOTHING;
    """)

    # 3. Drop email and password_hash columns from tenants table
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS email;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS password_hash;")


def downgrade() -> None:
    """Reverts user and tenant separation cleanly."""
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS email TEXT UNIQUE;")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS password_hash TEXT;")

    # Migrate back
    op.execute("""
        UPDATE tenants t
        SET email = u.email, password_hash = u.password_hash
        FROM users u
        WHERE t.id = u.tenant_id AND u.role = 'owner';
    """)

    op.execute("DROP TABLE IF EXISTS users CASCADE;")
