"""Circle of Trust feature

Revision ID: 002
Revises: 001
Create Date: 2025-08-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to trusted_contacts table
    op.add_column('trusted_contacts', sa.Column('contact_name', sa.String(), nullable=True))
    op.add_column('trusted_contacts', sa.Column('contact_phone_number', sa.String(), nullable=True))
    op.add_column('trusted_contacts', sa.Column('is_app_user', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('trusted_contacts', sa.Column('phone_contact_id', sa.String(), nullable=True))

    # SMS invitation fields
    op.add_column('trusted_contacts', sa.Column('sms_invitation_sent', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('trusted_contacts', sa.Column('sms_invitation_sent_at', sa.DateTime(), nullable=True))
    op.add_column('trusted_contacts', sa.Column('sms_message_id', sa.String(), nullable=True))

    # Create circle_of_trust_settings table
    op.create_table('circle_of_trust_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('max_contacts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('auto_import_contacts', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('sms_invitations_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('notification_preferences', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_circle_of_trust_settings_user_id_users')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_circle_of_trust_settings')),
        sa.UniqueConstraint('user_id', name=op.f('uq_circle_of_trust_settings_user_id'))
    )

    # Make contact_user_id nullable for non-app users
    op.alter_column('trusted_contacts', 'contact_user_id', nullable=True)

    # Update the unique constraint to allow multiple non-app contacts
    op.drop_constraint('uq_user_contact_pair', 'trusted_contacts', type_='unique')

    # Create a new partial unique constraint for app users only
    op.execute("""
        CREATE UNIQUE INDEX uq_user_contact_pair_app_users
        ON trusted_contacts (user_id, contact_user_id)
        WHERE contact_user_id IS NOT NULL
    """)

    # Add index for phone number lookup
    op.create_index('ix_trusted_contacts_phone_number', 'trusted_contacts', ['contact_phone_number'])


def downgrade() -> None:
    # Drop the partial unique index
    op.drop_index('uq_user_contact_pair_app_users', table_name='trusted_contacts')
    op.drop_index('ix_trusted_contacts_phone_number', table_name='trusted_contacts')

    # Restore the original unique constraint
    op.create_unique_constraint('uq_user_contact_pair', 'trusted_contacts', ['user_id', 'contact_user_id'])

    # Make contact_user_id non-nullable again
    op.alter_column('trusted_contacts', 'contact_user_id', nullable=False)

    # Drop circle_of_trust_settings table
    op.drop_table('circle_of_trust_settings')

    # Remove columns from trusted_contacts
    op.drop_column('trusted_contacts', 'sms_message_id')
    op.drop_column('trusted_contacts', 'sms_invitation_sent_at')
    op.drop_column('trusted_contacts', 'sms_invitation_sent')
    op.drop_column('trusted_contacts', 'phone_contact_id')
    op.drop_column('trusted_contacts', 'is_app_user')
    op.drop_column('trusted_contacts', 'contact_phone_number')
    op.drop_column('trusted_contacts', 'contact_name')
