"""add users.sms_unsubscribe_handled_at

Revision ID: 319905e9c08e
Revises: 7e8c5b62de29
Create Date: 2026-06-12 14:40:00.575140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '319905e9c08e'
down_revision: Union[str, None] = '7e8c5b62de29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Stamped when the worker auto-cancels a Stripe subscription
    # because the user has been SMS-unsubscribed for >= the grace
    # window. Idempotent marker: NULL means we haven't acted, set
    # means we have. Cleared on START so a future opt-out cycle gets
    # a fresh 14-day clock + re-action.
    op.add_column(
        "users",
        sa.Column(
            "sms_unsubscribe_handled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Partial index: the worker scan only cares about phones whose
    # current opt-out cycle is past the grace window AND haven't been
    # handled yet — keeps the scan O(small) regardless of user count.
    op.create_index(
        "ix_users_sms_unsubscribe_unhandled",
        "users",
        ["sms_unsubscribe_handled_at"],
        postgresql_where=sa.text("sms_unsubscribe_handled_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_sms_unsubscribe_unhandled", table_name="users")
    op.drop_column("users", "sms_unsubscribe_handled_at")
