"""create_user_two_factor_table

Revision ID: c3e4fea026e8
Revises: e6567a625ed3
Create Date: 2026-11-03 11:26:47.043892

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c3e4fea026e8'
down_revision: Union[str, None] = 'e6567a625ed3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_two_factor',
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('secret', sa.String(length=64), nullable=True),
        sa.Column('temp_secret', sa.String(length=64), nullable=True),
        sa.Column('recovery_codes', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('user_two_factor')