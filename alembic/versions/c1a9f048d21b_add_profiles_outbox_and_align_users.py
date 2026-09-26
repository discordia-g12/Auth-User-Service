"""add outbox and drop hashed_password from users

Revision ID: c1a9f048d21b
Revises: c13ea64b5665
Create Date: 2026-09-10 20:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1a9f048d21b"
down_revision: str | None = "c13ea64b5665"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drop hashed_password from users (delegated to Auth0)
    op.drop_column("users", "hashed_password")

    # 2. Create outbox_events table for Transactional Outbox Pattern
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("aggregate_type", sa.String(), nullable=False),
        sa.Column("aggregate_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_events")),
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.add_column("users", sa.Column("hashed_password", sa.String(), nullable=True))
