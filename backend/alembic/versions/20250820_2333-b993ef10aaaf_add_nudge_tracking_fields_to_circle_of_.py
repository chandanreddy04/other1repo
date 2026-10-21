"""Add nudge tracking fields to circle_of_trust_members

Revision ID: b993ef10aaaf
Revises: cd280b1aba86
Create Date: 2025-08-20 23:33:17.846493

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b993ef10aaaf'
down_revision: Union[str, None] = 'cd280b1aba86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add last nudged timestamp for rate limiting
    op.add_column('circle_of_trust_members',
        sa.Column('last_nudged_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove nudge tracking field
    op.drop_column('circle_of_trust_members', 'last_nudged_at')
