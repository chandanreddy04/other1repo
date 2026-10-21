"""add session_type column

Revision ID: b889d7e55423
Revises: a779c6b44312
Create Date: 2026-03-12 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b889d7e55423'
down_revision: Union[str, None] = 'a779c6b44312'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE session_type_enum AS ENUM ('checkin', 'sos')")
    op.add_column(
        'sessions',
        sa.Column(
            'session_type', sa.Enum('checkin', 'sos', name='session_type_enum'),
            nullable=False, server_default='checkin',
        ),
    )
    op.alter_column('sessions', 'session_type', server_default=None)


def downgrade() -> None:
    op.drop_column('sessions', 'session_type')
    op.execute("DROP TYPE session_type_enum")
