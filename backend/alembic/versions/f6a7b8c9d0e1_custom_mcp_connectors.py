"""custom (non-registry) remote MCP connectors: connector_connections custom fields

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-11 09:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('connector_connections', sa.Column('is_custom', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('connector_connections', sa.Column('display_name', sa.String(length=120), nullable=True))
    op.add_column('connector_connections', sa.Column('icon', sa.String(length=16), nullable=True))
    op.add_column('connector_connections', sa.Column('category', sa.String(length=48), nullable=True))
    op.add_column('connector_connections', sa.Column('transport', sa.String(length=8), nullable=False, server_default='http'))


def downgrade() -> None:
    op.drop_column('connector_connections', 'transport')
    op.drop_column('connector_connections', 'category')
    op.drop_column('connector_connections', 'icon')
    op.drop_column('connector_connections', 'display_name')
    op.drop_column('connector_connections', 'is_custom')
