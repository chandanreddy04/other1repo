"""replace_shared_info_with_structured_columns

Revision ID: a3c1f2d89e01
Revises: 5b896eb06b8c
Create Date: 2026-03-08 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c1f2d89e01'
down_revision: Union[str, None] = '5b896eb06b8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add structured columns
    op.add_column('alerts', sa.Column('last_known_latitude', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('last_known_longitude', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('last_location_address', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('destination', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('return_time', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('outfit_photo_url', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('user_name', sa.String(), nullable=True))
    op.add_column('alerts', sa.Column('user_phone', sa.String(), nullable=True))

    # Drop shared_info JSONB column and its GIN index
    op.drop_index('ix_alerts_shared_info', table_name='alerts')
    op.drop_column('alerts', 'shared_info')


def downgrade() -> None:
    # Re-add shared_info JSONB column
    op.add_column('alerts', sa.Column('shared_info', sa.JSON(), nullable=True))
    op.create_index('ix_alerts_shared_info', 'alerts', ['shared_info'], postgresql_using='gin')

    # Drop structured columns
    op.drop_column('alerts', 'user_phone')
    op.drop_column('alerts', 'user_name')
    op.drop_column('alerts', 'outfit_photo_url')
    op.drop_column('alerts', 'return_time')
    op.drop_column('alerts', 'destination')
    op.drop_column('alerts', 'last_location_address')
    op.drop_column('alerts', 'last_known_longitude')
    op.drop_column('alerts', 'last_known_latitude')
