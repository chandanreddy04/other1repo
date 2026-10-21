"""add sharing toggles to sessions

Revision ID: bbb8c3922a29
Revises: 1d68ee901fb8
Create Date: 2026-05-11 01:40:14.696002

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bbb8c3922a29'
down_revision: Union[str, None] = '1d68ee901fb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("battery_sharing_enabled", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("sessions", sa.Column("photo_sharing_enabled", sa.Boolean(), server_default="true", nullable=False))


def downgrade() -> None:
    op.drop_column("sessions", "photo_sharing_enabled")
    op.drop_column("sessions", "battery_sharing_enabled")
