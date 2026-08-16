"""Counting failed sign-ins, so the next one can be refused.

Revision ID: 024_login_attempts
Revises: 023_workout_sessions

Nothing rate-limited `/api/v1/auth/login`: no counter, no lockout, no backoff,
and no middleware at the edge either. This table is what the throttle in
`core.security.login_throttle` counts.

Two things about its shape are deliberate and would look like omissions
otherwise:

* **No `tenant_id`.** A sign-in has no tenant yet — establishing one is what it
  is for — so there is no workspace to scope to and rule 2 has nothing to bite
  on. Keying on a tenant would mean resolving the account before the rate limit
  applied, which is the lookup being limited.
* **`scope_key` is a digest, not a value.** An email address and an IP address
  are both personal data; a counter needs equality and gets nothing more. The
  plaintext alternative would be a log of every address anyone tried to sign in
  as, which is more sensitive than what it protects.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# 19 characters; `alembic_version.version_num` is VARCHAR(32).
revision: str = "024_login_attempts"
down_revision: str | None = "023_workout_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('account', 'client')", name="ck_login_attempts_scope"
        ),
    )
    # The counting query: scope + key + a time floor.
    op.create_index(
        "idx_login_attempts_scope_key_time",
        "login_attempts",
        ["scope", "scope_key", "attempted_at"],
    )
    # The sweep: every row older than the window, regardless of key. Without this
    # the prune degrades to a sequential scan as the table grows, which is exactly
    # when it is under attack and least able to afford one.
    op.create_index("idx_login_attempts_time", "login_attempts", ["attempted_at"])


def downgrade() -> None:
    """Fully reversible, and loses only counters.

    Dropping this table forgets in-window failures, so a caller mid-lockout is
    served again. That is the whole content of the table — it holds no user data
    and nothing references it.
    """
    op.drop_index("idx_login_attempts_time", table_name="login_attempts")
    op.drop_index("idx_login_attempts_scope_key_time", table_name="login_attempts")
    op.drop_table("login_attempts")
