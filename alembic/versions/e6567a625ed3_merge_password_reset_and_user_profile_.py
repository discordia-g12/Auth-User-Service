"""merge password reset and user profile edit heads

Revision ID: e6567a625ed3
Revises: 7c1e5a9d2b40, d1a9f048d21c
Create Date: 2026-09-27 21:32:44.851557

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6567a625ed3'
down_revision: Union[str, None] = ('7c1e5a9d2b40', 'd1a9f048d21c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass