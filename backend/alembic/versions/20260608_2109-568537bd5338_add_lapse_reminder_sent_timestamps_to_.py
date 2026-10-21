"""add lapse reminder sent timestamps to subscriptions

Revision ID: 568537bd5338
Revises: 95f40aa02dab
Create Date: 2026-06-08 21:09:43.557479

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '568537bd5338'
down_revision: Union[str, None] = '95f40aa02dab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "lapse_reminder_7d_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "lapse_reminder_1d_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "lapse_reminder_1d_sent_at")
    op.drop_column("subscriptions", "lapse_reminder_7d_sent_at")
