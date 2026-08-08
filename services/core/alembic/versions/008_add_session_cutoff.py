"""Add users.sessions_valid_from, a per-user access-token cutoff

Revision ID: 008_session_cutoff
Revises: 007_add_oidc
Create Date: 2026-08-08 00:00:00.000000

Revoking "every session" previously revoked only the refresh tokens. The access
tokens already in circulation stayed valid until they expired on their own, up to
twelve hours later — after a password change, after a detected refresh-token
replay, and now after an identity provider tells us over the back channel that
the identity behind a session is gone.

The existing denylist cannot express this. It keys on ``jti``, and a ``jti`` only
becomes known when its token is presented, so "all outstanding tokens for this
user" is not a set anything can enumerate. A cutoff timestamp compared against
the token's ``iat`` covers all of them in one row and one comparison.

Nullable with no backfill on purpose: NULL means "no cutoff has ever been set",
which is true of every existing account, and stamping them all with NOW() would
sign every active user out on deploy for no reason.
"""
from collections.abc import Sequence

from alembic import op

revision: str = '008_session_cutoff'
down_revision: str | None = '007_add_oidc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS sessions_valid_from TIMESTAMPTZ;")


def downgrade() -> None:
    """Drop the column.

    Losing it re-opens the window described above for any session issued before
    a cutoff was set, which is the same position the system was in before this
    migration — so the rollback is lossy in effect but not in data anyone can
    still act on: refresh tokens revoked alongside the cutoff stay revoked, so a
    downgrade cannot resurrect a session for longer than one access-token TTL.
    """
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS sessions_valid_from;")
