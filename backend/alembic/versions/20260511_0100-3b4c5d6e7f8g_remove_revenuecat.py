"""remove revenuecat_original_transaction_id column

RevenueCat has been replaced by direct Stripe subscriptions.
Drop the column that tracked RC transaction IDs.

Revision ID: 3b4c5d6e7f8g
Revises: 2a3b4c5d6e7f
Create Date: 2026-05-11 01:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3b4c5d6e7f8g"
down_revision: str | None = "2a3b4c5d6e7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("subscriptions", "revenuecat_original_transaction_id")


def downgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("revenuecat_original_transaction_id", sa.String(), nullable=True),
    )
