"""session purged_at and cancelled_at

Revision ID: 69bb7b6ae2f0
Revises: e5f6a7b8c9d0
Create Date: 2026-07-19 11:02:03.694025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69bb7b6ae2f0'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # purged_at: when captured data was ACTUALLY deleted (stamped by
    # purge_session_data — covers the admin early-purge path, which never
    # touches the purge_after schedule).
    op.add_column(
        "sessions", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True)
    )
    # cancelled_at: neutral session-end anchor for admin-cancelled sessions
    # (actual_return_time would falsely claim the owner marked themselves
    # safe). Drives the retention-floor math and purged-date fallback.
    op.add_column(
        "sessions", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("sessions", "cancelled_at")
    op.drop_column("sessions", "purged_at")
