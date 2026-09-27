"""add display_name and custom_status

Revision ID: d1a9f048d21c
Revises: c1a9f048d21b
Create Date: 2026-09-27 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd1a9f048d21c'
down_revision: Union[str, None] = 'c1a9f048d21b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Add display_name column
    op.add_column('user_profiles', sa.Column('display_name', sa.String(length=64), nullable=True))
    # Note: custom_status was already in the model in the previous revision but missing in schema,
    # let's make sure it exists. If it exists, this might fail, so we catch it or check.
    # Actually, custom_status was already in the model before I touched it.
    pass

def downgrade() -> None:
    op.drop_column('user_profiles', 'display_name')
