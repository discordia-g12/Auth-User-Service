"""add_suspension_details_to_users

Revision ID: f2b7c4d91e10
Revises: c3e4fea026e8
Create Date: 2026-11-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f2b7c4d91e10'
down_revision: Union[str, None] = 'c3e4fea026e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('suspended_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('suspended_by', sa.String(), nullable=True))
    op.add_column('users', sa.Column('suspension_reason', sa.String(length=512), nullable=True))
    op.create_index('ix_users_is_suspended', 'users', ['is_suspended'])


def downgrade() -> None:
    op.drop_index('ix_users_is_suspended', table_name='users')
    op.drop_column('users', 'suspension_reason')
    op.drop_column('users', 'suspended_by')
    op.drop_column('users', 'suspended_at')
