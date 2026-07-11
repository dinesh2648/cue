"""meetings list scalability: composite (scope, created_at) indexes

Revision ID: cc33dd44ee55
Revises: bb22cc33dd44
Create Date: 2026-07-11 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'cc33dd44ee55'
down_revision: Union[str, None] = 'bb22cc33dd44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Support "WHERE org_id=? / owner_user_id=? ORDER BY created_at DESC LIMIT/OFFSET" without
    # loading the whole workspace's meetings into memory.
    op.create_index("ix_meetings_org_created", "meetings", ["org_id", "created_at"])
    op.create_index("ix_meetings_owner_created", "meetings", ["owner_user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_meetings_owner_created", table_name="meetings")
    op.drop_index("ix_meetings_org_created", table_name="meetings")
