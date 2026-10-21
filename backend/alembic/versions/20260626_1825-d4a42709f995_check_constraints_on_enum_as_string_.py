"""CHECK constraints on enum-as-string columns

Revision ID: d4a42709f995
Revises: ee5051ee1091
Create Date: 2026-06-26 18:25:26.260453

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4a42709f995'
down_revision: str | None = 'ee5051ee1091'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# These columns store enum values as plain strings with no DB-level validation
# (unlike the native-enum columns elsewhere). Add CHECK constraints so an
# invalid value can't be persisted.
_CHECKS = {
    "ck_subscriptions_plan_type": (
        "subscriptions",
        "plan_type IN ('monthly','annual','family_monthly','family_annual')",
    ),
    "ck_subscriptions_status": (
        "subscriptions",
        "status IN ('active','expired','cancelled','pending')",
    ),
    "ck_subscriptions_source": (
        "subscriptions",
        "source IN ('stripe_gift','stripe_web','referral','promotion','admin')",
    ),
    "ck_referrals_status": (
        "referrals",
        "status IN ('pending','completed','expired')",
    ),
    "ck_sponsorship_requests_status": (
        "sponsorship_requests",
        "status IN ('pending','fulfilled')",
    ),
    "ck_family_plan_members_role": (
        "family_plan_members",
        "role IN ('owner','member')",
    ),
}


def upgrade() -> None:
    for name, (table, condition) in _CHECKS.items():
        op.create_check_constraint(name, table, condition)


def downgrade() -> None:
    for name, (table, _) in _CHECKS.items():
        op.drop_constraint(name, table, type_="check")
