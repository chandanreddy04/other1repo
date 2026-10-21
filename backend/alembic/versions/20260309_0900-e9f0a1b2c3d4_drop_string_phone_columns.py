"""drop_string_phone_columns

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-03-09 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the denormalized string phone columns now that all code uses FK references
    op.drop_index('ix_users_phone_number', table_name='users')
    op.drop_column('users', 'phone_number')
    op.drop_column('subscriptions', 'phone_number')
    op.drop_column('subscriptions', 'gifted_by_phone')
    op.drop_column('referrals', 'referee_phone')

    # Drop old contact_phone_number column and its index from circle_of_trust_members
    op.drop_index('ix_circle_of_trust_members_phone_number', table_name='circle_of_trust_members')
    op.drop_column('circle_of_trust_members', 'contact_phone_number')


def downgrade() -> None:
    # Re-add the string columns
    op.add_column('circle_of_trust_members', sa.Column('contact_phone_number', sa.String(), nullable=True))
    op.create_index('ix_circle_of_trust_members_phone_number', 'circle_of_trust_members', ['contact_phone_number'])

    op.add_column('referrals', sa.Column('referee_phone', sa.String(), nullable=True))
    op.add_column('subscriptions', sa.Column('gifted_by_phone', sa.String(), nullable=True))
    op.add_column('subscriptions', sa.Column('phone_number', sa.String(), nullable=True))
    op.add_column('users', sa.Column('phone_number', sa.String(), nullable=True))
    op.create_index('ix_users_phone_number', 'users', ['phone_number'], unique=True)
