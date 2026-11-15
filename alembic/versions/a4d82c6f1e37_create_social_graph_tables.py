"""create_social_graph_tables

Revision ID: a4d82c6f1e37
Revises: f2b7c4d91e10
Create Date: 2026-11-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a4d82c6f1e37'
down_revision: Union[str, None] = 'f2b7c4d91e10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'friend_requests',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('requester_id', sa.String(), nullable=False),
        sa.Column('addressee_id', sa.String(), nullable=False),
        sa.Column('message', sa.String(length=190), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('requester_id <> addressee_id', name=op.f('ck_friend_requests_not_self')),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'canceled')", name=op.f('ck_friend_requests_status_valid')
        ),
        sa.ForeignKeyConstraint(
            ['requester_id'], ['users.id'], name='fk_friend_requests_requester_id_users', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['addressee_id'], ['users.id'], name='fk_friend_requests_addressee_id_users', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name='pk_friend_requests'),
    )
    op.create_index(
        'uq_friend_requests_pending_pair',
        'friend_requests',
        ['requester_id', 'addressee_id'],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index('ix_friend_requests_addressee_id_status', 'friend_requests', ['addressee_id', 'status'])

    op.create_table(
        'friendships',
        sa.Column('user_low_id', sa.String(), nullable=False),
        sa.Column('user_high_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('user_low_id <> user_high_id', name=op.f('ck_friendships_not_self')),
        sa.ForeignKeyConstraint(
            ['user_low_id'], ['users.id'], name='fk_friendships_user_low_id_users', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['user_high_id'], ['users.id'], name='fk_friendships_user_high_id_users', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('user_low_id', 'user_high_id', name='pk_friendships'),
    )
    op.create_index('ix_friendships_user_high_id', 'friendships', ['user_high_id'])

    op.create_table(
        'user_blocks',
        sa.Column('blocker_id', sa.String(), nullable=False),
        sa.Column('blocked_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('blocker_id <> blocked_id', name=op.f('ck_user_blocks_not_self')),
        sa.ForeignKeyConstraint(
            ['blocker_id'], ['users.id'], name='fk_user_blocks_blocker_id_users', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['blocked_id'], ['users.id'], name='fk_user_blocks_blocked_id_users', ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('blocker_id', 'blocked_id', name='pk_user_blocks'),
    )
    op.create_index('ix_user_blocks_blocked_id', 'user_blocks', ['blocked_id'])


def downgrade() -> None:
    op.drop_index('ix_user_blocks_blocked_id', table_name='user_blocks')
    op.drop_table('user_blocks')
    op.drop_index('ix_friendships_user_high_id', table_name='friendships')
    op.drop_table('friendships')
    op.drop_index('ix_friend_requests_addressee_id_status', table_name='friend_requests')
    op.drop_index('uq_friend_requests_pending_pair', table_name='friend_requests')
    op.drop_table('friend_requests')
