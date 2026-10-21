"""drop_unused_profile_visibility_settings

Revision ID: 2f3362e534de
Revises: 072962b223ec
Create Date: 2026-03-14 09:28:58.677239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f3362e534de'
down_revision: Union[str, None] = '072962b223ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('user_settings', 'share_profile_photo')
    op.drop_column('user_settings', 'share_last_seen')


def downgrade() -> None:
    op.add_column('user_settings', sa.Column('share_last_seen', sa.Boolean(), server_default='true'))
    op.add_column('user_settings', sa.Column('share_profile_photo', sa.Boolean(), server_default='true'))
