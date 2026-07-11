"""per-user capability toggles: users.capabilities

Revision ID: aa11bb22cc33
Revises: f6a7b8c9d0e1
Create Date: 2026-07-11 10:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa11bb22cc33'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('capabilities', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'capabilities')
