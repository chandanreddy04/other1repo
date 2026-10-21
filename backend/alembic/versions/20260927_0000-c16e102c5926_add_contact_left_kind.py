"""Add contact_left to notification_kind_enum.

Owner decision: a member who leaves a Circle from the web page
(POST /circles/{code}/leave) now gets the same owner cascade notification
as the SMS STOP cascade, with leave-specific wording ("Circle member left")
for the "others remain" case — so it needs its own outbox kind
(NotificationKind.CONTACT_LEFT) to keep the audit trail honest about which
trigger fired. The emptied-circle kinds (circle_emptied /
circle_emptied_mid_session) are unchanged and shared by both reasons.
Additive only — single-release migration (no app version has shipped rows
of this kind yet).

Revision ID: c16e102c5926
Revises: fe2c7404af02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c16e102c5926"
down_revision: str | None = "fe2c7404af02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; escape
    # via autocommit_block. IF NOT EXISTS makes the statement idempotent.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notification_kind_enum ADD VALUE IF NOT EXISTS "
            "'contact_left'"
        )


def downgrade() -> None:
    # Postgres does not support removing values from an enum. Downgrade is
    # intentionally a no-op; the label is left in place and unused if the
    # deploy reverts.
    pass
