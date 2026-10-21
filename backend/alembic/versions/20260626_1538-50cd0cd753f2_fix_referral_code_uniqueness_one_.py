"""fix referral_code uniqueness; one referral per referee

Revision ID: 50cd0cd753f2
Revises: db6c675fb517
Create Date: 2026-06-26 15:38:48.925078

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '50cd0cd753f2'
down_revision: str | None = 'db6c675fb517'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # referrals.referral_code stored the *referrer's* share code, which is the
    # same value for every redeemer — so a UNIQUE index meant the 2nd person to
    # use any code hit an IntegrityError (500) and max_referral_redemptions was
    # unreachable. Recreate it non-unique (still want the lookup index).
    op.drop_index("ix_referrals_referral_code", table_name="referrals")
    op.create_index("ix_referrals_referral_code", "referrals", ["referral_code"])

    # The correct uniqueness is "one referral per referee" — enforce it at the
    # DB so the check-then-insert in referral_service can't double-credit a
    # referee under a race. Partial (referee_user_id is nullable historically).
    op.create_index(
        "ix_referrals_one_per_referee",
        "referrals",
        ["referee_user_id"],
        unique=True,
        postgresql_where=sa.text("referee_user_id IS NOT NULL"),
    )

    # referrer_user_id backs get_redemption_count (count per referrer); unindexed.
    op.create_index(
        "ix_referrals_referrer_user_id", "referrals", ["referrer_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_referrals_referrer_user_id", table_name="referrals")
    op.drop_index("ix_referrals_one_per_referee", table_name="referrals")
    op.drop_index("ix_referrals_referral_code", table_name="referrals")
    op.create_index(
        "ix_referrals_referral_code", "referrals", ["referral_code"], unique=True
    )
