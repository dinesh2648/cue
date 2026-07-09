"""advisory context: user/company profiles + evolving meeting state

Adds the Context Foundation for the multi-agent advisor:
- users.profile (JSON), users.custom_context (Text) — personal advisory context
- organizations.description (Text), organizations.profile (JSON) — company advisory context
- meetings.running_summary (Text), meetings.context_json (JSON) — evolving Meeting Context

All added with server_defaults so existing rows backfill cleanly (no NULLs to special-case).

Revision ID: f1a2b3c4d5e6
Revises: c9543b5df1f2
Create Date: 2026-07-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'c9543b5df1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('profile', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column('users', sa.Column('custom_context', sa.Text(), nullable=False, server_default=''))
    op.add_column('organizations', sa.Column('description', sa.Text(), nullable=False, server_default=''))
    op.add_column('organizations', sa.Column('profile', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column('meetings', sa.Column('running_summary', sa.Text(), nullable=False, server_default=''))
    op.add_column('meetings', sa.Column('context_json', sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    op.drop_column('meetings', 'context_json')
    op.drop_column('meetings', 'running_summary')
    op.drop_column('organizations', 'profile')
    op.drop_column('organizations', 'description')
    op.drop_column('users', 'custom_context')
    op.drop_column('users', 'profile')
