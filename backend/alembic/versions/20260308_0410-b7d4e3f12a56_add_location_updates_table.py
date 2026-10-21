"""add_location_updates_table

Revision ID: b7d4e3f12a56
Revises: a3c1f2d89e01
Create Date: 2026-03-08 04:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'b7d4e3f12a56'
down_revision: Union[str, None] = 'a3c1f2d89e01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'location_updates',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('session_id', UUID(as_uuid=True), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('latitude', sa.String(), nullable=False),
        sa.Column('longitude', sa.String(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_location_updates_session_id', 'location_updates', ['session_id'])
    op.create_index(
        'ix_location_updates_session_recorded',
        'location_updates',
        ['session_id', 'recorded_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_location_updates_session_recorded', table_name='location_updates')
    op.drop_index('ix_location_updates_session_id', table_name='location_updates')
    op.drop_table('location_updates')
