"""create password_reset_requests

Per-email rate limit for password reset requests (ADR-006).

Revision ID: 7c1e5a9d2b40
Revises: REPLACE_WITH_CURRENT_HEAD
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c1e5a9d2b40"
# TODO antes de mergear: reemplazar por el ID que devuelve `alembic heads` en este repo.
down_revision: str | None = "c1a9f048d21b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_reset_requests")),
    )
    op.create_index(
        "ix_password_reset_requests_email_hash_requested_at",
        "password_reset_requests",
        ["email_hash", "requested_at"],
    )
    op.create_index(
        op.f("ix_password_reset_requests_requested_at"),
        "password_reset_requests",
        ["requested_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_password_reset_requests_requested_at"), table_name="password_reset_requests")
    op.drop_index("ix_password_reset_requests_email_hash_requested_at", table_name="password_reset_requests")
    op.drop_table("password_reset_requests")
