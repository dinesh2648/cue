"""ask conversation history: ask_threads + ask_messages

Revision ID: dd44ee55ff66
Revises: cc33dd44ee55
Create Date: 2026-07-11 13:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'dd44ee55ff66'
down_revision: Union[str, None] = 'cc33dd44ee55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ask_threads',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False, server_default='New chat'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ask_threads_user_id', 'ask_threads', ['user_id'])
    op.create_index('ix_ask_threads_user_updated', 'ask_threads', ['user_id', 'updated_at'])

    op.create_table(
        'ask_messages',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('thread_id', sa.String(length=32), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False, server_default='user'),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['thread_id'], ['ask_threads.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ask_messages_thread_id', 'ask_messages', ['thread_id'])
    op.create_index('ix_ask_messages_thread_created', 'ask_messages', ['thread_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_ask_messages_thread_created', table_name='ask_messages')
    op.drop_index('ix_ask_messages_thread_id', table_name='ask_messages')
    op.drop_table('ask_messages')
    op.drop_index('ix_ask_threads_user_updated', table_name='ask_threads')
    op.drop_index('ix_ask_threads_user_id', table_name='ask_threads')
    op.drop_table('ask_threads')
