"""drop_unused_notification_settings

Revision ID: 14bc9a74a645
Revises: 2f3362e534de
Create Date: 2026-03-14 09:47:31.355233

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14bc9a74a645'
down_revision: Union[str, None] = '2f3362e534de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('user_settings', 'push_notifications_enabled')
    op.drop_column('user_settings', 'alert_notifications')
    op.drop_column('user_settings', 'check_in_reminders')
    op.drop_column('user_settings', 'circle_updates')
    op.drop_column('user_settings', 'marketing_notifications')


def downgrade() -> None:
    op.add_column('user_settings', sa.Column('marketing_notifications', sa.Boolean(), server_default='false'))
    op.add_column('user_settings', sa.Column('circle_updates', sa.Boolean(), server_default='true'))
    op.add_column('user_settings', sa.Column('check_in_reminders', sa.Boolean(), server_default='true'))
    op.add_column('user_settings', sa.Column('alert_notifications', sa.Boolean(), server_default='true'))
    op.add_column('user_settings', sa.Column('push_notifications_enabled', sa.Boolean(), server_default='true'))
