"""create outbox_events

Revision ID: 76e895f52e31
Revises: c13ea64b5665
Create Date: 2026-09-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '76e895f52e31'
down_revision: Union[str, None] = 'c13ea64b5665'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'outbox_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('aggregate_type', sa.String(), nullable=False),
        sa.Column('aggregate_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox_events')),
    )
    op.create_index(op.f('ix_outbox_events_aggregate_id'), 'outbox_events', ['aggregate_id'], unique=False)
    op.create_index(op.f('ix_outbox_events_processed_at'), 'outbox_events', ['processed_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_outbox_events_processed_at'), table_name='outbox_events')
    op.drop_index(op.f('ix_outbox_events_aggregate_id'), table_name='outbox_events')
    op.drop_table('outbox_events')
