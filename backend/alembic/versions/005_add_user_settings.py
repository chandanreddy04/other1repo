"""Add user settings table

Revision ID: 005
Revises: 004
Create Date: 2025-01-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    # Create user_settings table
    op.create_table('user_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('push_notifications_enabled', sa.Boolean(), nullable=True, default=True),
        sa.Column('alert_notifications', sa.Boolean(), nullable=True, default=True),
        sa.Column('check_in_reminders', sa.Boolean(), nullable=True, default=True),
        sa.Column('circle_updates', sa.Boolean(), nullable=True, default=True),
        sa.Column('marketing_notifications', sa.Boolean(), nullable=True, default=False),
        sa.Column('location_sharing_enabled', sa.Boolean(), nullable=True, default=True),
        sa.Column('share_profile_photo', sa.Boolean(), nullable=True, default=True),
        sa.Column('share_last_seen', sa.Boolean(), nullable=True, default=True),
        sa.Column('theme', sa.String(), nullable=True, default='light'),
        sa.Column('language', sa.String(), nullable=True, default='en'),
        sa.Column('time_format', sa.String(), nullable=True, default='12h'),
        sa.Column('distance_unit', sa.String(), nullable=True, default='mi'),
        sa.Column('auto_alert_delay_minutes', sa.Integer(), nullable=True, default=15),
        sa.Column('emergency_message', sa.String(), nullable=True),
        sa.Column('custom_settings', postgresql.JSON(astext_type=sa.Text()), nullable=True, default={}),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_user_settings_user_id'),
        sa.PrimaryKeyConstraint('id', name='pk_user_settings'),
        sa.UniqueConstraint('user_id', name='uq_user_settings_user_id')
    )

    # Create index on user_id for faster lookups
    op.create_index('ix_user_settings_user_id', 'user_settings', ['user_id'])


def downgrade():
    op.drop_index('ix_user_settings_user_id', table_name='user_settings')
    op.drop_table('user_settings')
