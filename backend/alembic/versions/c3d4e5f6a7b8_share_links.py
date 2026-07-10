"""public shareable links for meeting artifacts

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-10 02:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'share_links',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('meeting_id', sa.String(length=32), nullable=False),
        sa.Column('org_id', sa.String(length=64), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('scopes', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('view_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['meeting_id'], ['meetings.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_share_links_token', 'share_links', ['token'], unique=True)
    op.create_index('ix_share_links_meeting_id', 'share_links', ['meeting_id'])
    op.create_index('ix_share_links_org_id', 'share_links', ['org_id'])


def downgrade() -> None:
    op.drop_index('ix_share_links_org_id', table_name='share_links')
    op.drop_index('ix_share_links_meeting_id', table_name='share_links')
    op.drop_index('ix_share_links_token', table_name='share_links')
    op.drop_table('share_links')
