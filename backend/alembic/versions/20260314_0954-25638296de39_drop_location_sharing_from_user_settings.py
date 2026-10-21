"""drop_location_sharing_from_user_settings

Revision ID: 25638296de39
Revises: 14bc9a74a645
Create Date: 2026-03-14 09:54:37.627025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '25638296de39'
down_revision: Union[str, None] = '14bc9a74a645'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('user_settings', 'location_sharing_enabled')


def downgrade() -> None:
    op.add_column('user_settings', sa.Column('location_sharing_enabled', sa.Boolean(), server_default='true'))
