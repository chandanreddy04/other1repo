"""make alert session_id nullable remove duress

Revision ID: a779c6b44312
Revises: 2c0004c6ad29
Create Date: 2026-03-12 11:26:12.987393

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a779c6b44312'
down_revision: Union[str, None] = '2c0004c6ad29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('alerts', 'session_id', nullable=True)
    op.execute("ALTER TYPE alert_type_enum RENAME TO alert_type_enum_old")
    op.execute("CREATE TYPE alert_type_enum AS ENUM ('missed_session', 'reminder', 'panic')")
    op.execute(
        "ALTER TABLE alerts ALTER COLUMN alert_type TYPE alert_type_enum "
        "USING alert_type::text::alert_type_enum"
    )
    op.execute("DROP TYPE alert_type_enum_old")


def downgrade() -> None:
    op.execute("ALTER TYPE alert_type_enum RENAME TO alert_type_enum_old")
    op.execute(
        "CREATE TYPE alert_type_enum AS ENUM "
        "('reminder', 'missed_session', 'panic', 'duress')"
    )
    op.execute(
        "ALTER TABLE alerts ALTER COLUMN alert_type TYPE alert_type_enum "
        "USING alert_type::text::alert_type_enum"
    )
    op.execute("DROP TYPE alert_type_enum_old")
    op.alter_column('alerts', 'session_id', nullable=False)
