"""add sponsorship_sign_in_tokens table

Replaces the JWT-based sponsorship magic-link token (mint_sponsorship_token /
decode_sponsorship_token, removed from app/services/account_deletion.py) with
a short, opaque, one-time DB token so the SMS link can be short
({SHORT_DOMAIN}/s/p/{token}) and single-use (used_at). See
app/models/sponsorship_sign_in_token.py.

Revision ID: dc8eabb7ad50
Revises: b4a1c7e2d908
Create Date: 2026-09-27 02:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = 'dc8eabb7ad50'
down_revision: str | None = 'b4a1c7e2d908'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'sponsorship_sign_in_tokens',
        sa.Column('token', sa.String(length=12), primary_key=True),
        sa.Column(
            'phone_number_id',
            UUID(as_uuid=True),
            sa.ForeignKey('phone_numbers.id'),
            nullable=False,
        ),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        'ix_sponsorship_sign_in_tokens_phone_number_id',
        'sponsorship_sign_in_tokens',
        ['phone_number_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_sponsorship_sign_in_tokens_phone_number_id',
        table_name='sponsorship_sign_in_tokens',
    )
    op.drop_table('sponsorship_sign_in_tokens')
