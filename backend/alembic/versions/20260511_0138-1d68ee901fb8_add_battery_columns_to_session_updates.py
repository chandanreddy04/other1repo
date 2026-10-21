"""add battery columns to session_updates

Revision ID: 1d68ee901fb8
Revises: 1a49a8f3bc4a
Create Date: 2026-05-11 01:38:35.623278

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1d68ee901fb8'
down_revision: Union[str, None] = '1a49a8f3bc4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_updates", sa.Column("battery_level", sa.Float(), nullable=True))
    op.add_column("session_updates", sa.Column("battery_state", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("session_updates", "battery_state")
    op.drop_column("session_updates", "battery_level")
