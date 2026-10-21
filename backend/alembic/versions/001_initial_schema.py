"""Initial schema

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table('users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('phone_number', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('full_name', sa.String(), nullable=False),
        sa.Column('profile_photo_url', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_verified', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users'))
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_phone_number'), 'users', ['phone_number'], unique=True)

    # Create enums - using sa.Enum with create_type=False to avoid duplicate creation
    contact_status_enum = sa.Enum('pending', 'active', 'blocked', name='contact_status_enum', create_type=False)
    priority_level_enum = sa.Enum('primary', 'secondary', name='priority_level_enum', create_type=False)
    checkin_status_enum = sa.Enum('active', 'completed', 'missed', 'cancelled', name='checkin_status_enum', create_type=False)
    alert_type_enum = sa.Enum('reminder', 'missed_checkin', 'panic', 'duress', name='alert_type_enum', create_type=False)
    alert_status_enum = sa.Enum('sent', 'delivered', 'acknowledged', 'failed', name='alert_status_enum', create_type=False)

    # Create enum types explicitly
    op.execute("CREATE TYPE contact_status_enum AS ENUM ('pending', 'active', 'blocked')")
    op.execute("CREATE TYPE priority_level_enum AS ENUM ('primary', 'secondary')")
    op.execute("CREATE TYPE checkin_status_enum AS ENUM ('active', 'completed', 'missed', 'cancelled')")
    op.execute("CREATE TYPE alert_type_enum AS ENUM ('reminder', 'missed_checkin', 'panic', 'duress')")
    op.execute("CREATE TYPE alert_status_enum AS ENUM ('sent', 'delivered', 'acknowledged', 'failed')")

    # Create trusted_contacts table
    op.create_table('trusted_contacts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('contact_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('priority_level', postgresql.ENUM('primary', 'secondary', name='priority_level_enum', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('pending', 'active', 'blocked', name='contact_status_enum', create_type=False), nullable=False),
        sa.Column('invitation_code', sa.String(), nullable=True),
        sa.Column('invited_at', sa.DateTime(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['contact_user_id'], ['users.id'], name=op.f('fk_trusted_contacts_contact_user_id_users')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_trusted_contacts_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_trusted_contacts')),
        sa.UniqueConstraint('invitation_code', name=op.f('uq_trusted_contacts_invitation_code')),
        sa.UniqueConstraint('user_id', 'contact_user_id', name='uq_user_contact_pair')
    )

    # Create checkins table
    op.create_table('checkins',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('expected_return_time', sa.DateTime(), nullable=False),
        sa.Column('actual_return_time', sa.DateTime(), nullable=True),
        sa.Column('destination', sa.Text(), nullable=True),
        sa.Column('outfit_photo_url', sa.String(), nullable=True),
        sa.Column('outfit_photo_uploaded_at', sa.DateTime(), nullable=True),
        sa.Column('location_sharing_enabled', sa.Boolean(), nullable=True),
        sa.Column('last_known_latitude', sa.String(), nullable=True),
        sa.Column('last_known_longitude', sa.String(), nullable=True),
        sa.Column('last_location_update', sa.DateTime(), nullable=True),
        sa.Column('status', postgresql.ENUM('active', 'completed', 'missed', 'cancelled', name='checkin_status_enum', create_type=False), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_checkins_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_checkins'))
    )

    # Create alerts table
    op.create_table('alerts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('checkin_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sent_to_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('alert_type', postgresql.ENUM('reminder', 'missed_checkin', 'panic', 'duress', name='alert_type_enum', create_type=False), nullable=False),
        sa.Column('status', postgresql.ENUM('sent', 'delivered', 'acknowledged', 'failed', name='alert_status_enum', create_type=False), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.Column('delivered_at', sa.DateTime(), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.Column('push_notification_id', sa.String(), nullable=True),
        sa.Column('sms_message_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['checkin_id'], ['checkins.id'], name=op.f('fk_alerts_checkin_id_checkins')),
        sa.ForeignKeyConstraint(['sent_to_user_id'], ['users.id'], name=op.f('fk_alerts_sent_to_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_alerts'))
    )


def downgrade() -> None:
    op.drop_table('alerts')
    op.drop_table('checkins')
    op.drop_table('trusted_contacts')
    op.drop_index(op.f('ix_users_phone_number'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')

    # Drop enums
    op.execute("DROP TYPE IF EXISTS alert_status_enum")
    op.execute("DROP TYPE IF EXISTS alert_type_enum")
    op.execute("DROP TYPE IF EXISTS checkin_status_enum")
    op.execute("DROP TYPE IF EXISTS priority_level_enum")
    op.execute("DROP TYPE IF EXISTS contact_status_enum")
