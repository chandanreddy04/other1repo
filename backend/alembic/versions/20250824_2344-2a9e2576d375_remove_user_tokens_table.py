"""Remove user_tokens table

Revision ID: 2a9e2576d375
Revises: 49d2fbdfc8cc
Create Date: 2025-08-24 23:44:07.538688

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a9e2576d375'
down_revision: Union[str, None] = '49d2fbdfc8cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('DROP TABLE IF EXISTS user_tokens')


def downgrade() -> None:
    # Recreate the user_tokens table
    op.create_table('user_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_user_tokens_user_id_users'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token')
    )
    op.create_index(op.f('ix_user_tokens_token'), 'user_tokens', ['token'], unique=True)
