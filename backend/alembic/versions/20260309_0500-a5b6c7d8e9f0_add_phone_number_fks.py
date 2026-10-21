"""add_phone_number_fks

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-03-09 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users: add phone_number_id FK, rename is_verified → phone_ownership_verified
    op.add_column('users', sa.Column('phone_number_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_users_phone_number_id_phone_numbers',
        'users', 'phone_numbers',
        ['phone_number_id'], ['id'],
    )
    op.alter_column('users', 'is_verified', new_column_name='phone_ownership_verified')

    # Subscriptions: add phone_number_id and gifted_by_phone_id FKs
    op.add_column('subscriptions', sa.Column('phone_number_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_subscriptions_phone_number_id_phone_numbers',
        'subscriptions', 'phone_numbers',
        ['phone_number_id'], ['id'],
    )
    op.add_column('subscriptions', sa.Column('gifted_by_phone_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_subscriptions_gifted_by_phone_id_phone_numbers',
        'subscriptions', 'phone_numbers',
        ['gifted_by_phone_id'], ['id'],
    )

    # Referrals: add referee_phone_id FK
    op.add_column('referrals', sa.Column('referee_phone_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_referrals_referee_phone_id_phone_numbers',
        'referrals', 'phone_numbers',
        ['referee_phone_id'], ['id'],
    )

    # Circle of trust members: add contact_phone_number_id FK
    op.add_column('circle_of_trust_members', sa.Column('contact_phone_number_id', UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_cot_members_contact_phone_number_id_phones',
        'circle_of_trust_members', 'phone_numbers',
        ['contact_phone_number_id'], ['id'],
    )


def downgrade() -> None:
    # Circle of trust members
    op.drop_constraint('fk_cot_members_contact_phone_number_id_phones', 'circle_of_trust_members', type_='foreignkey')
    op.drop_column('circle_of_trust_members', 'contact_phone_number_id')

    # Referrals
    op.drop_constraint('fk_referrals_referee_phone_id_phone_numbers', 'referrals', type_='foreignkey')
    op.drop_column('referrals', 'referee_phone_id')

    # Subscriptions
    op.drop_constraint('fk_subscriptions_gifted_by_phone_id_phone_numbers', 'subscriptions', type_='foreignkey')
    op.drop_column('subscriptions', 'gifted_by_phone_id')
    op.drop_constraint('fk_subscriptions_phone_number_id_phone_numbers', 'subscriptions', type_='foreignkey')
    op.drop_column('subscriptions', 'phone_number_id')

    # Users
    op.alter_column('users', 'phone_ownership_verified', new_column_name='is_verified')
    op.drop_constraint('fk_users_phone_number_id_phone_numbers', 'users', type_='foreignkey')
    op.drop_column('users', 'phone_number_id')
