"""llm_usage: per-call token + cost accounting

Revision ID: e7f8a9b0c1d2
Revises: dd44ee55ff66
Create Date: 2026-07-16 09:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'dd44ee55ff66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'llm_usage',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=True),
        sa.Column('meeting_id', sa.String(length=32), nullable=True),
        sa.Column('user_id', sa.String(length=64), nullable=True),
        sa.Column('call_type', sa.String(length=32), nullable=False),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cache_read_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cache_write_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tool_calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_usd', sa.Float(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_llm_usage_org_id', 'llm_usage', ['org_id'])
    op.create_index('ix_llm_usage_meeting_id', 'llm_usage', ['meeting_id'])
    op.create_index('ix_llm_usage_user_id', 'llm_usage', ['user_id'])
    op.create_index('ix_llm_usage_call_type', 'llm_usage', ['call_type'])
    op.create_index('ix_llm_usage_created_at', 'llm_usage', ['created_at'])
    op.create_index('ix_llm_usage_org_created', 'llm_usage', ['org_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_llm_usage_org_created', table_name='llm_usage')
    op.drop_index('ix_llm_usage_created_at', table_name='llm_usage')
    op.drop_index('ix_llm_usage_call_type', table_name='llm_usage')
    op.drop_index('ix_llm_usage_user_id', table_name='llm_usage')
    op.drop_index('ix_llm_usage_meeting_id', table_name='llm_usage')
    op.drop_index('ix_llm_usage_org_id', table_name='llm_usage')
    op.drop_table('llm_usage')
