"""per-user suggestions: suggestions.recipient_user_id

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-10 03:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('suggestions', sa.Column('recipient_user_id', sa.String(length=64), nullable=True))
    op.create_index('ix_suggestions_recipient_user_id', 'suggestions', ['recipient_user_id'])


def downgrade() -> None:
    op.drop_index('ix_suggestions_recipient_user_id', table_name='suggestions')
    op.drop_column('suggestions', 'recipient_user_id')
