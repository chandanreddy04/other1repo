"""drop_alert_snapshot_columns

Revision ID: d2e3f4a5b6c7
Revises: c1a2b3d4e5f6
Create Date: 2026-03-09 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('alerts', 'last_known_latitude')
    op.drop_column('alerts', 'last_known_longitude')
    op.drop_column('alerts', 'last_location_address')
    op.drop_column('alerts', 'destination')
    op.drop_column('alerts', 'return_time')
    op.drop_column('alerts', 'outfit_photo_url')
    op.drop_column('alerts', 'user_name')
    op.drop_column('alerts', 'user_phone')


def downgrade() -> None:
    op.add_column('alerts', sa.Column('user_phone', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('user_name', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('outfit_photo_url', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('return_time', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('destination', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('last_location_address', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('last_known_longitude', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('last_known_latitude', sa.String(), nullable=True))
