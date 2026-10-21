"""add_max_referral_redemptions_to_users

Revision ID: e0bf5a724cd2
Revises: 2de3761a03eb
Create Date: 2026-03-12 14:58:59.779251

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e0bf5a724cd2'
down_revision: Union[str, None] = '2de3761a03eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("max_referral_redemptions", sa.Integer(), server_default="6", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "max_referral_redemptions")
