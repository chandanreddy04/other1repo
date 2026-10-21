"""add_circle_invite_code_to_users

Revision ID: 072962b223ec
Revises: e0bf5a724cd2
Create Date: 2026-03-13 10:00:00.000000

"""
import secrets
import string
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "072962b223ec"
down_revision: Union[str, None] = "e0bf5a724cd2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _random_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(8))


def upgrade() -> None:
    # Add nullable column first
    op.add_column(
        "users",
        sa.Column("circle_invite_code", sa.String(), nullable=True),
    )

    # Backfill existing users with unique codes
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id FROM users")).fetchall()
    for (user_id,) in users:
        # Generate unique code, retry on collision
        while True:
            code = _random_code()
            existing = conn.execute(
                sa.text(
                    "SELECT 1 FROM users WHERE circle_invite_code = :code"
                ),
                {"code": code},
            ).fetchone()
            if not existing:
                break
        conn.execute(
            sa.text(
                "UPDATE users SET circle_invite_code = :code WHERE id = :id"
            ),
            {"code": code, "id": user_id},
        )

    # Add unique index
    op.create_index(
        "ix_users_circle_invite_code",
        "users",
        ["circle_invite_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_circle_invite_code", table_name="users")
    op.drop_column("users", "circle_invite_code")
