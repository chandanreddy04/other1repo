"""Rename checkins to sessions

Revision ID: cd280b1aba86
Revises: 007
Create Date: 2025-08-20 20:30:56.739045

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cd280b1aba86'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename the checkins table to sessions
    op.rename_table('checkins', 'sessions')

    # Rename the checkin_status_enum to session_status_enum
    op.execute("ALTER TYPE checkin_status_enum RENAME TO session_status_enum")

    # Rename the foreign key constraint in alerts table
    op.drop_constraint('fk_alerts_checkin_id_checkins', 'alerts', type_='foreignkey')
    op.alter_column('alerts', 'checkin_id', new_column_name='session_id')
    op.create_foreign_key(
        'fk_alerts_session_id_sessions',
        'alerts',
        'sessions',
        ['session_id'],
        ['id']
    )


def downgrade() -> None:
    # Rename the sessions table back to checkins
    op.rename_table('sessions', 'checkins')

    # Rename the session_status_enum back to checkin_status_enum
    op.execute("ALTER TYPE session_status_enum RENAME TO checkin_status_enum")

    # Rename the foreign key constraint in alerts table
    op.drop_constraint('fk_alerts_session_id_sessions', 'alerts', type_='foreignkey')
    op.alter_column('alerts', 'session_id', new_column_name='checkin_id')
    op.create_foreign_key(
        'fk_alerts_checkin_id_checkins',
        'alerts',
        'checkins',
        ['checkin_id'],
        ['id']
    )
