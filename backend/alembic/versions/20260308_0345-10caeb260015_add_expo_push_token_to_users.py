"""add_expo_push_token_to_users

Revision ID: 10caeb260015
Revises: a1b2c3d4e5f6
Create Date: 2026-03-08 03:45:37.411374

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10caeb260015'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('expo_push_token', sa.String(), nullable=True))
    op.create_index('ix_users_expo_push_token', 'users', ['expo_push_token'])


def downgrade() -> None:
    op.drop_index('ix_users_expo_push_token', table_name='users')
    op.drop_column('users', 'expo_push_token')
