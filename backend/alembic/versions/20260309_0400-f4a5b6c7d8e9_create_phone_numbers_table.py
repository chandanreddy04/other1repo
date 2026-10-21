"""create_phone_numbers_table

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-03-09 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'phone_numbers',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('number', sa.String(), nullable=False),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_phone_numbers_number', 'phone_numbers', ['number'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_phone_numbers_number', table_name='phone_numbers')
    op.drop_table('phone_numbers')
