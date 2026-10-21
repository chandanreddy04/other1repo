"""drop_user_settings_table

Revision ID: a7b8c9d0e1f2
Revises: 25638296de39
Create Date: 2026-03-14 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = '25638296de39'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('user_settings')


def downgrade() -> None:
    op.create_table(
        'user_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), unique=True, nullable=False),
        sa.Column('theme', sa.String(), server_default='light'),
        sa.Column('language', sa.String(), server_default='en'),
        sa.Column('time_format', sa.String(), server_default='12h'),
        sa.Column('distance_unit', sa.String(), server_default='mi'),
        sa.Column('auto_alert_delay_minutes', sa.Integer(), server_default='15'),
        sa.Column('emergency_message', sa.String(), nullable=True),
        sa.Column('custom_settings', sa.JSON(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
    )
