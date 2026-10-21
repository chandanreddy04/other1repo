"""backfill circle invite codes and enforce admin phones

Two data fixes:
  1. Backfill circle_invite_code / share_code for any account that lacks one.
     Older accounts predate get_or_create setting these, and without a
     circle_invite_code the shared /c/{code} invite link resolves to nothing
     ("Invalid circle invite code"). Login also backfills going forward.
  2. Grant admin to the designated admin phone numbers. Login re-enforces this
     idempotently (settings.ADMIN_PHONE_NUMBERS).

Revision ID: c5f8b2a1e9d4
Revises: b2e4c6a8f019
Create Date: 2026-07-04 12:00:00.000000

"""
import secrets
import string
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c5f8b2a1e9d4'
down_revision: str | None = 'b2e4c6a8f019'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CODE_CHARS = string.ascii_uppercase + string.digits


def _unique_code(used: set[str]) -> str:
    # 8-char A-Z0-9 (~2.8e12 space); collisions among the in-memory set are
    # vanishingly unlikely, and `used` is seeded with all existing codes.
    while True:
        code = "".join(secrets.choice(_CODE_CHARS) for _ in range(8))
        if code not in used:
            used.add(code)
            return code


def upgrade() -> None:
    conn = op.get_bind()

    # 1a) circle_invite_code
    used = {
        r[0]
        for r in conn.execute(
            sa.text(
                "SELECT circle_invite_code FROM users "
                "WHERE circle_invite_code IS NOT NULL"
            )
        )
    }
    for (row_id,) in conn.execute(
        sa.text("SELECT id FROM users WHERE circle_invite_code IS NULL")
    ).fetchall():
        conn.execute(
            sa.text("UPDATE users SET circle_invite_code = :code WHERE id = :id"),
            {"code": _unique_code(used), "id": row_id},
        )

    # 1b) share_code
    used = {
        r[0]
        for r in conn.execute(
            sa.text("SELECT share_code FROM users WHERE share_code IS NOT NULL")
        )
    }
    for (row_id,) in conn.execute(
        sa.text("SELECT id FROM users WHERE share_code IS NULL")
    ).fetchall():
        conn.execute(
            sa.text("UPDATE users SET share_code = :code WHERE id = :id"),
            {"code": _unique_code(used), "id": row_id},
        )

    # 2) Grant admin to the designated phone numbers (fixed literals — the
    # admin accounts, not user input).
    conn.execute(
        sa.text(
            "UPDATE users SET is_admin = true WHERE phone_number_id IN ("
            "SELECT id FROM phone_numbers "
            "WHERE number IN ('+15102849127', '+15182608694'))"
        )
    )


def downgrade() -> None:
    # Data backfill — codes are not reverted (removing them would re-break
    # invite links). Only the admin grants are undone.
    op.get_bind().execute(
        sa.text(
            "UPDATE users SET is_admin = false WHERE phone_number_id IN ("
            "SELECT id FROM phone_numbers "
            "WHERE number IN ('+15102849127', '+15182608694'))"
        )
    )
