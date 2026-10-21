"""remove_is_app_user_from_circle_of_trust

Revision ID: 5b896eb06b8c
Revises: 10caeb260015
Create Date: 2026-03-08 03:50:01.589437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b896eb06b8c'
down_revision: Union[str, None] = '10caeb260015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('circle_of_trust_members', 'is_app_user')


def downgrade() -> None:
    op.add_column(
        'circle_of_trust_members',
        sa.Column('is_app_user', sa.Boolean(), nullable=False, server_default='true'),
    )
