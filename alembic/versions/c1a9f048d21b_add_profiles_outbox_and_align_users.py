"""add profiles, outbox, and drop hashed_password from users

Revision ID: c1a9f048d21b
Revises: 23753b693bdd
Create Date: 2026-09-10 20:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1a9f048d21b"
down_revision: str | None = "23753b693bdd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update users table
    op.add_column(
        "users",
        sa.Column(
            "is_suspended",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.drop_column("users", "hashed_password")

    # 2. Create user_profiles table
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("bio", sa.String(), nullable=True),
        sa.Column("activity_status", sa.String(), nullable=True, server_default="offline"),
        sa.Column("custom_status", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_profiles_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_profiles")),
    )
    op.create_index(op.f("ix_user_profiles_username"), "user_profiles", ["username"], unique=True)

    # 3. Create outbox_events table
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
    op.drop_index(op.f("ix_user_profiles_username"), table_name="user_profiles")
    op.drop_table("user_profiles")
    op.add_column("users", sa.Column("hashed_password", sa.String(), nullable=True))
    op.alter_column("users", "email", existing_type=sa.String(), nullable=False)
    op.drop_column("users", "is_suspended")
