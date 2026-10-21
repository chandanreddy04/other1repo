"""rename location_updates to session_updates

Revision ID: 1a49a8f3bc4a
Revises: 3b4c5d6e7f8g
Create Date: 2026-05-11 01:36:08.775315

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '1a49a8f3bc4a'
down_revision: Union[str, None] = '3b4c5d6e7f8g'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table("location_updates", "session_updates")
    op.execute("ALTER TABLE session_updates RENAME CONSTRAINT pk_location_updates TO pk_session_updates")
    op.execute("ALTER TABLE session_updates RENAME CONSTRAINT fk_location_updates_session_id_sessions TO fk_session_updates_session_id_sessions")
    op.execute("ALTER INDEX ix_location_updates_session_id RENAME TO ix_session_updates_session_id")
    op.execute("ALTER INDEX ix_location_updates_session_recorded RENAME TO ix_session_updates_session_recorded")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_session_updates_session_recorded RENAME TO ix_location_updates_session_recorded")
    op.execute("ALTER INDEX ix_session_updates_session_id RENAME TO ix_location_updates_session_id")
    op.execute("ALTER TABLE session_updates RENAME CONSTRAINT fk_session_updates_session_id_sessions TO fk_location_updates_session_id_sessions")
    op.execute("ALTER TABLE session_updates RENAME CONSTRAINT pk_session_updates TO pk_location_updates")
    op.rename_table("session_updates", "location_updates")
