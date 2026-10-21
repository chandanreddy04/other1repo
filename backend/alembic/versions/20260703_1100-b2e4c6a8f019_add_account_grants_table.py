"""add account_grants table

Admin-managed per-account access grants: lifetime complimentary access plus an
optional fixed OTP login code for accounts that can't receive SMS (store
reviewers). See app/models/account_grant.py.

Revision ID: b2e4c6a8f019
Revises: a7c3e9b1d05f
Create Date: 2026-07-03 11:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'b2e4c6a8f019'
down_revision: str | None = 'a7c3e9b1d05f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'account_grants',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'phone_number_id',
            UUID(as_uuid=True),
            sa.ForeignKey('phone_numbers.id'),
            nullable=False,
        ),
        sa.Column('label', sa.String(), nullable=False, server_default=''),
        sa.Column('otp_code', sa.String(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('phone_number_id', name='uq_account_grants_phone_number_id'),
    )


def downgrade() -> None:
    op.drop_table('account_grants')
