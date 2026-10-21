"""rename circle of trust tables

Revision ID: 003
Revises: 002
Create Date: 2025-01-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # Rename the table from trusted_contacts to circle_of_trust_members
    op.rename_table('trusted_contacts', 'circle_of_trust_members')

    # Update index names
    op.drop_index('ix_trusted_contacts_phone_number', table_name='circle_of_trust_members')
    op.create_index('ix_circle_of_trust_members_phone_number', 'circle_of_trust_members', ['contact_phone_number'])

    # Update foreign key constraint names
    op.drop_constraint('fk_trusted_contacts_user_id_users', 'circle_of_trust_members', type_='foreignkey')
    op.drop_constraint('fk_trusted_contacts_contact_user_id_users', 'circle_of_trust_members', type_='foreignkey')

    op.create_foreign_key('fk_circle_of_trust_members_user_id_users', 'circle_of_trust_members', 'users', ['user_id'], ['id'])
    op.create_foreign_key('fk_circle_of_trust_members_contact_user_id_users', 'circle_of_trust_members', 'users', ['contact_user_id'], ['id'])

    # Update unique constraint names
    op.drop_constraint('uq_trusted_contacts_invitation_code', 'circle_of_trust_members', type_='unique')
    op.create_unique_constraint('uq_circle_of_trust_members_invitation_code', 'circle_of_trust_members', ['invitation_code'])


def downgrade():
    # Rename the table back
    op.rename_table('circle_of_trust_members', 'trusted_contacts')

    # Restore original index names
    op.drop_index('ix_circle_of_trust_members_phone_number', table_name='trusted_contacts')
    op.create_index('ix_trusted_contacts_phone_number', 'trusted_contacts', ['contact_phone_number'])

    # Restore original foreign key constraint names
    op.drop_constraint('fk_circle_of_trust_members_user_id_users', 'trusted_contacts', type_='foreignkey')
    op.drop_constraint('fk_circle_of_trust_members_contact_user_id_users', 'trusted_contacts', type_='foreignkey')

    op.create_foreign_key('fk_trusted_contacts_user_id_users', 'trusted_contacts', 'users', ['user_id'], ['id'])
    op.create_foreign_key('fk_trusted_contacts_contact_user_id_users', 'trusted_contacts', 'users', ['contact_user_id'], ['id'])

    # Restore original unique constraint names
    op.drop_constraint('uq_circle_of_trust_members_invitation_code', 'trusted_contacts', type_='unique')
    op.create_unique_constraint('uq_trusted_contacts_invitation_code', 'trusted_contacts', ['invitation_code'])
