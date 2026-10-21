"""add sessions.purge_after for extensible data retention

Post-session data (photos, location trail) now survives
SESSION_DATA_RETENTION_DAYS (7) after completion instead of being purged on
the next worker tick, and the owner can extend the window from History.
NULL = legacy row from the purge-immediately era (already purgeable).

Revision ID: c4e2d3b0e112
Revises: b3f1c2a9d001
Create Date: 2026-07-02 19:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4e2d3b0e112'
down_revision: str | None = 'b3f1c2a9d001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "purge_after")
