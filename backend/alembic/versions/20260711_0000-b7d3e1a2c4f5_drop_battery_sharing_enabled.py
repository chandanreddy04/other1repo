"""drop sessions.battery_sharing_enabled

Battery capture/sharing is now always on — reading the level needs no OS
permission and a dying phone is safety-critical context — so the per-session
toggle column (and its UI) are removed.

Revision ID: b7d3e1a2c4f5
Revises: f1a2b3c4d5e6
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7d3e1a2c4f5"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("sessions", "battery_sharing_enabled")


def downgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "battery_sharing_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # Match the ORM (default at app level, no server default).
    op.alter_column("sessions", "battery_sharing_enabled", server_default=None)
