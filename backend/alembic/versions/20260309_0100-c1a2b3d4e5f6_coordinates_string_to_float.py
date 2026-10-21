"""coordinates_string_to_float

Revision ID: c1a2b3d4e5f6
Revises: b7d4e3f12a56
Create Date: 2026-03-09 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b7d4e3f12a56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # location_updates: latitude and longitude from String to Float
    op.alter_column(
        'location_updates', 'latitude',
        type_=sa.Float(),
        postgresql_using='latitude::double precision',
    )
    op.alter_column(
        'location_updates', 'longitude',
        type_=sa.Float(),
        postgresql_using='longitude::double precision',
    )

    # sessions: last_known_latitude and last_known_longitude from String to Float
    op.alter_column(
        'sessions', 'last_known_latitude',
        type_=sa.Float(),
        postgresql_using='last_known_latitude::double precision',
    )
    op.alter_column(
        'sessions', 'last_known_longitude',
        type_=sa.Float(),
        postgresql_using='last_known_longitude::double precision',
    )


def downgrade() -> None:
    op.alter_column(
        'sessions', 'last_known_longitude',
        type_=sa.String(),
    )
    op.alter_column(
        'sessions', 'last_known_latitude',
        type_=sa.String(),
    )
    op.alter_column(
        'location_updates', 'longitude',
        type_=sa.String(),
    )
    op.alter_column(
        'location_updates', 'latitude',
        type_=sa.String(),
    )
