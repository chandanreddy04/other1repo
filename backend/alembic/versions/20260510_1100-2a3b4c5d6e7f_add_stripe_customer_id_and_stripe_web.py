"""add stripe_customer_id and stripe_web source

Add stripe_customer_id (NOT NULL) to users, stripe_subscription_id to
subscriptions. STRIPE_WEB source is stored as plain varchar string, so
no enum migration needed.

Revision ID: 2a3b4c5d6e7f
Revises: 1f2e3d4c5b6a
Create Date: 2026-05-10 11:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2a3b4c5d6e7f"
down_revision: str | None = "1f2e3d4c5b6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "stripe_customer_id",
            sa.String(),
            nullable=False,
            server_default="pending:bootstrap",
        ),
    )
    op.alter_column("users", "stripe_customer_id", server_default=None)
    op.create_unique_constraint("uq_users_stripe_customer_id", "users", ["stripe_customer_id"])
    op.create_index("ix_users_stripe_customer_id", "users", ["stripe_customer_id"])

    op.add_column(
        "subscriptions",
        sa.Column("stripe_subscription_id", sa.String(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_subscriptions_stripe_subscription_id",
        "subscriptions",
        ["stripe_subscription_id"],
    )
    op.create_index(
        "ix_subscriptions_stripe_subscription_id",
        "subscriptions",
        ["stripe_subscription_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_stripe_subscription_id", table_name="subscriptions")
    op.drop_constraint("uq_subscriptions_stripe_subscription_id", "subscriptions", type_="unique")
    op.drop_column("subscriptions", "stripe_subscription_id")

    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_constraint("uq_users_stripe_customer_id", "users", type_="unique")
    op.drop_column("users", "stripe_customer_id")
