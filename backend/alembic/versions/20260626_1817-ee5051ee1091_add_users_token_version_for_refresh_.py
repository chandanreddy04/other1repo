"""add users.token_version for refresh revocation

Revision ID: ee5051ee1091
Revises: ad4d714fa3b9
Create Date: 2026-06-26 18:17:52.711983

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ee5051ee1091'
down_revision: str | None = 'ad4d714fa3b9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
