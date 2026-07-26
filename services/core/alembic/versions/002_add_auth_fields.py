"""Add email and password_hash to tenants
Revision ID: 002_add_auth_fields
Revises: 001_initial_schema
Create Date: 2026-07-26 18:25:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = '002_add_auth_fields'
down_revision: str | None = '001_initial_schema'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS email TEXT UNIQUE;")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS password_hash TEXT;")

def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS email;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS password_hash;")
