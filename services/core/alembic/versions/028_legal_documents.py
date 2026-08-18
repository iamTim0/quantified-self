"""The imprint and the privacy policy, as text an operator can change.

Revision ID: 028_legal_documents
Revises: 027_field_history_backfill

Both documents existed only as TSX components carrying `[placeholder]` markers
for the company name, the address and the contact details. Filling them in meant
editing source and rebuilding the dashboard image, so a deployment run by anyone
who does not do that served a public legal notice naming nobody — the exact
condition § 5 DDG exists to prevent.

The table is deployment-wide, and that is not an oversight about rule 2. An
imprint identifies whoever operates the service; there is no workspace inside it
that could own one, and the pages are read by visitors for whom no tenant exists.
`oidc_providers` is unscoped for the same reason.

Empty rather than seeded. Rule 9 forbids inventing data on startup, and a seeded
imprint would be worse than most seed data: a document that looks filled in and
names a fictional operator. An absent row means the shipped default is rendered,
which is a template that says on its face that it is one.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "028_legal_documents"
down_revision: str | None = "027_field_history_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "legal_documents",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("slug", sa.String(32), nullable=False),
        # Text rather than a bounded String: a privacy policy is a document, and a
        # column that truncates one silently is worse than no column. The request
        # model caps the size where a caller can be told about it.
        sa.Column("body_de", sa.Text(), nullable=True),
        sa.Column("body_en", sa.Text(), nullable=True),
        sa.Column(
            "updated_by",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # One row per document, enforced here rather than by the endpoint alone: two
    # rows for `privacy` would make which policy is in force depend on row order.
    op.create_unique_constraint("uq_legal_documents_slug", "legal_documents", ["slug"])


def downgrade() -> None:
    """Fully reversible, and this one genuinely loses text.

    Dropping the table discards whatever the operator wrote, and the pages fall
    back to the shipped default documents — placeholders and all. That is a real
    loss of content rather than of derived state, so it is worth saying plainly:
    export the two documents before rolling this migration back.

    It is nonetheless the correct downgrade. Leaving the table behind would strand
    rows no code reads, and a schema that half-remembers a reverted feature is how
    the next migration acquires a constraint nobody can explain.
    """
    op.drop_constraint("uq_legal_documents_slug", "legal_documents", type_="unique")
    op.drop_table("legal_documents")
