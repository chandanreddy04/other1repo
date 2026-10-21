"""make session_updates.latitude/longitude nullable

A session_update row may now be battery-only: an opportunistic heartbeat can
report a battery reading even when location is off (coords null). Location and
battery are derived independently on the Session model, so a battery-only row
never blanks the last-known location.

Revision ID: a1c2e3f4b5d6
Revises: b7d3e1a2c4f5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c2e3f4b5d6"
down_revision: str | None = "b7d3e1a2c4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("session_updates", "latitude", existing_type=sa.Float(), nullable=True)
    op.alter_column("session_updates", "longitude", existing_type=sa.Float(), nullable=True)


def downgrade() -> None:
    # Reverting requires every row to have coords; battery-only rows would block
    # the NOT NULL. Drop them first so the constraint can be re-applied.
    op.execute("DELETE FROM session_updates WHERE latitude IS NULL OR longitude IS NULL")
    op.alter_column("session_updates", "latitude", existing_type=sa.Float(), nullable=False)
    op.alter_column("session_updates", "longitude", existing_type=sa.Float(), nullable=False)
