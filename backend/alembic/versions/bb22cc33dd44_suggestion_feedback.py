"""answer feedback loop: suggestion_feedback table

Revision ID: bb22cc33dd44
Revises: aa11bb22cc33
Create Date: 2026-07-11 11:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bb22cc33dd44'
down_revision: Union[str, None] = 'aa11bb22cc33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'suggestion_feedback',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('suggestion_id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=64), nullable=False),
        sa.Column('meeting_id', sa.String(length=32), nullable=False, server_default=''),
        sa.Column('rating', sa.String(length=8), nullable=False, server_default=''),
        sa.Column('correction', sa.Text(), nullable=False, server_default=''),
        sa.Column('query_text', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['suggestion_id'], ['suggestions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_suggestion_feedback_suggestion_id', 'suggestion_feedback', ['suggestion_id'])
    op.create_index('ix_suggestion_feedback_user_id', 'suggestion_feedback', ['user_id'])
    op.create_index('ix_suggestion_feedback_meeting_id', 'suggestion_feedback', ['meeting_id'])


def downgrade() -> None:
    op.drop_index('ix_suggestion_feedback_meeting_id', table_name='suggestion_feedback')
    op.drop_index('ix_suggestion_feedback_user_id', table_name='suggestion_feedback')
    op.drop_index('ix_suggestion_feedback_suggestion_id', table_name='suggestion_feedback')
    op.drop_table('suggestion_feedback')
