"""rename referral_code to share_code on users

Revision ID: 5f0ef10d904b
Revises: 8cc8b5f56f61
Create Date: 2026-05-08 23:40:00.103594

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5f0ef10d904b'
down_revision: Union[str, None] = '8cc8b5f56f61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "referral_code", new_column_name="share_code")


def downgrade() -> None:
    op.alter_column("users", "share_code", new_column_name="referral_code")
