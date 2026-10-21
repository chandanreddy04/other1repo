"""add subscription cancelled_by_sms_unsubscribe_at

Revision ID: 8e4f8ec5df12
Revises: 319905e9c08e
Create Date: 2026-06-12 15:28:57.666855

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e4f8ec5df12'
down_revision: Union[str, None] = '319905e9c08e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Stamped when sms_unsubscribe_tasks auto-cancels a sub because the
    # owner ignored the post-STOP grace window. Lets `record_opt_in`
    # know which subs to un-cancel on START — we never touch
    # cancellations the user initiated themselves via Stripe portal.
    op.add_column(
        "subscriptions",
        sa.Column(
            "cancelled_by_sms_unsubscribe_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "cancelled_by_sms_unsubscribe_at")
