"""auto-join (autopilot) ON by default

New users get autopilot=true (server default), and existing users are flipped on so meetings
auto-join with zero manual intervention. Each user can still turn it off at /settings.

Revision ID: b2c3d4e5f6a7
Revises: a7b8c9d0e1f2
Create Date: 2026-07-10 01:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Flip the column default on for new rows…
    op.alter_column('users', 'autopilot', server_default=sa.true())
    # …and turn it on for everyone who exists today (zero-touch auto-join by default).
    op.execute(sa.text("UPDATE users SET autopilot = true"))


def downgrade() -> None:
    op.alter_column('users', 'autopilot', server_default=sa.false())
