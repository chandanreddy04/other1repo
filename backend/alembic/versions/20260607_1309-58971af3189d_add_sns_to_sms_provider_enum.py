"""add sns to sms_provider_enum

Revision ID: 58971af3189d
Revises: 17ef24d04e9d
Create Date: 2026-06-07 13:09:38.780591

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '58971af3189d'
down_revision: Union[str, None] = '17ef24d04e9d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in any
    # Postgres version. Alembic wraps each migration in a transaction by
    # default, so we have to escape it explicitly via autocommit_block.
    # IF NOT EXISTS makes the statement idempotent.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE sms_provider_enum ADD VALUE IF NOT EXISTS 'sns'")


def downgrade() -> None:
    # Postgres does not support removing values from an enum. Downgrade
    # is intentionally a no-op; the 'sns' label is left in place and
    # ignored by application code if the deploy reverts to ACS-only.
    pass
