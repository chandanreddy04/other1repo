"""add_resolved_alert_status

Revision ID: 2de3761a03eb
Revises: b889d7e55423
Create Date: 2026-03-12 12:52:32.052167

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '2de3761a03eb'
down_revision: Union[str, None] = 'b889d7e55423'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE alert_status_enum ADD VALUE IF NOT EXISTS 'resolved'")
    op.add_column("alerts", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alerts", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "failed_at")
    op.drop_column("alerts", "resolved_at")
    # PostgreSQL does not support removing enum values; recreate if needed
