"""drop_session_location_snapshot_columns

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-03-09 08:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, None] = 'c7d8e9f0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('sessions', 'last_known_latitude')
    op.drop_column('sessions', 'last_known_longitude')
    op.drop_column('sessions', 'last_location_update')


def downgrade() -> None:
    op.add_column('sessions', sa.Column('last_location_update', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sessions', sa.Column('last_known_longitude', sa.Float(), nullable=True))
    op.add_column('sessions', sa.Column('last_known_latitude', sa.Float(), nullable=True))
