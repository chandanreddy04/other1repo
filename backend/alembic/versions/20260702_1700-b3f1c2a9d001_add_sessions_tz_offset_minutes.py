"""add sessions.tz_offset_minutes for local-time alert copy

Client's UTC offset (minutes east of UTC) captured at session creation so
alert SMS can render "expected back by 10:30 PM" in the owner's local time.
Nullable — older clients don't send it; alert copy falls back to a no-time
variant.

Revision ID: b3f1c2a9d001
Revises: d4a42709f995
Create Date: 2026-07-02 17:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3f1c2a9d001'
down_revision: str | None = 'd4a42709f995'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("tz_offset_minutes", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "tz_offset_minutes")
