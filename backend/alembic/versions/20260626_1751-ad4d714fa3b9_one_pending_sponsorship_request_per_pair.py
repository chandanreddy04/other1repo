"""one pending sponsorship request per pair

Revision ID: ad4d714fa3b9
Revises: 8ce884503ae7
Create Date: 2026-06-26 17:51:57.196462

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ad4d714fa3b9'
down_revision: str | None = '8ce884503ae7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # At most one PENDING sponsorship request per (requester, target) pair, so
    # get_pending_for_pair can't find two (it uses scalar_one_or_none) and the
    # gift-webhook bookkeeping can't break. Fulfilled rows are unconstrained.
    op.create_index(
        "ix_sr_one_pending_per_pair",
        "sponsorship_requests",
        ["requester_phone_id", "target_phone_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sr_one_pending_per_pair", table_name="sponsorship_requests"
    )
