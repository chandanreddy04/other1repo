"""allow comp in subscriptions source CHECK

Complimentary/comped access granted via the admin-managed AccountGrant table
(store reviewers, VIPs, comps) is a distinct subscription source ('comp') so
it's excludable from real-revenue analytics. See app/models/account_grant.py
and subscription_service.ensure_comp_access.

Revision ID: a7c3e9b1d05f
Revises: e6a4f5d2a334
Create Date: 2026-07-03 10:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c3e9b1d05f'
down_revision: str | None = 'e6a4f5d2a334'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "subscriptions"
_NAME = "ck_subscriptions_source"
_OLD = "source IN ('stripe_gift','stripe_web','referral','promotion','admin')"
_NEW = (
    "source IN ('stripe_gift','stripe_web','referral','promotion','admin','comp')"
)


def upgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _NEW)


def downgrade() -> None:
    op.drop_constraint(_NAME, _TABLE, type_="check")
    op.create_check_constraint(_NAME, _TABLE, _OLD)
