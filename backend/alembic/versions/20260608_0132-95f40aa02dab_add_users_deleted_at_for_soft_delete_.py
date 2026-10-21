"""add users.deleted_at for soft-delete grace

Revision ID: 95f40aa02dab
Revises: 58971af3189d
Create Date: 2026-06-08 01:32:47.421400

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95f40aa02dab'
down_revision: Union[str, None] = '58971af3189d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index: the hard-purge worker only cares about rows scheduled
    # for purge, which is a tiny fraction of the table. A partial index
    # keeps the index small and the scan O(scheduled-for-purge) rather
    # than O(total-users).
    op.create_index(
        "ix_users_deleted_at",
        "users",
        ["deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_deleted_at", table_name="users")
    op.drop_column("users", "deleted_at")
