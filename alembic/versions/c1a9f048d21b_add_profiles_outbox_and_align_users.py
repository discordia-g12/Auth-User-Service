"""add outbox and drop hashed_password from users

Revision ID: c1a9f048d21b
Revises: 76e895f52e31
Create Date: 2026-09-10 20:50:00.000000

"""

from collections.abc import Sequence
from typing import Union
import sqlalchemy as sa

from alembic import op

revision: str = "c1a9f048d21b"
down_revision: Union[str, None] = '76e895f52e31'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drop hashed_password from users (delegated to Auth0)
    op.drop_column("users", "hashed_password")


def downgrade() -> None:
    op.add_column("users", sa.Column("hashed_password", sa.String(), nullable=True))