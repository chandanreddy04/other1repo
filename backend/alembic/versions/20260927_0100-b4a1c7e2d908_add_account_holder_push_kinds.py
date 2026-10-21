"""Add account_holder_unsubscribed and account_holder_subscription_cancelled
to notification_kind_enum.

Owner decision: every push auditable. The two account-holder STOP pushes
(notification_helpers.send_account_holder_unsubscribed and
send_account_holder_subscription_cancelled) now route through the
notification_deliveries outbox instead of calling the push provider
directly, so both need their own outbox kind. Additive only —
single-release migration (no app version has shipped rows of these kinds
yet).

Revision ID: b4a1c7e2d908
Revises: c16e102c5926
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b4a1c7e2d908"
down_revision: str | None = "c16e102c5926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; escape
    # via autocommit_block. IF NOT EXISTS makes the statement idempotent.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notification_kind_enum ADD VALUE IF NOT EXISTS "
            "'account_holder_unsubscribed'"
        )
        op.execute(
            "ALTER TYPE notification_kind_enum ADD VALUE IF NOT EXISTS "
            "'account_holder_subscription_cancelled'"
        )


def downgrade() -> None:
    # Postgres does not support removing values from an enum. Downgrade is
    # intentionally a no-op; the two labels are left in place and unused if
    # the deploy reverts.
    pass
