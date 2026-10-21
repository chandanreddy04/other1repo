"""add users had_prior_billing_history for re-signup free trial gating

Revision ID: b33191340593
Revises: 568537bd5338
Create Date: 2026-06-09 21:41:23.668436

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b33191340593'
down_revision: Union[str, None] = '568537bd5338'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "had_prior_billing_history",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "had_prior_billing_history")
