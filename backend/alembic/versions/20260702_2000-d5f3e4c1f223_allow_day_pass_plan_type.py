"""allow day_pass in subscriptions plan_type CHECK

One-time 24h day pass ($0.99, Stripe mode=payment) joins the plan types —
the episodic rung below a subscription (flow-review 3.9).

Revision ID: d5f3e4c1f223
Revises: c4e2d3b0e112
Create Date: 2026-07-02 20:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd5f3e4c1f223'
down_revision: str | None = 'c4e2d3b0e112'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "subscriptions"
_NAME = "ck_subscriptions_plan_type"
_OLD = "plan_type IN ('monthly','annual','family_monthly','family_annual')"
_NEW = (
    "plan_type IN ('monthly','annual','family_monthly','family_annual','day_pass')"
)


def upgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)


def downgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _OLD)
