"""Add group_plan_grace and subscription_lapse to notification_kind_enum.

Owner decision: every push auditable. The group-plan grace push (group_plan_service) and the
subscription-lapse SMS+push (sub_lapse_notifications) now route through the
notification_deliveries outbox instead of calling the push provider directly,
so both need their own outbox kind. Additive only — single-release migration
(no app version has shipped rows of these kinds yet).

Revision ID: a2b3c4d5e6f7
Revises: d75a707d6ba9
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "d75a707d6ba9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; escape
    # via autocommit_block. IF NOT EXISTS makes the statement idempotent.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notification_kind_enum ADD VALUE IF NOT EXISTS "
            "'group_plan_grace'"
        )
        op.execute(
            "ALTER TYPE notification_kind_enum ADD VALUE IF NOT EXISTS "
            "'subscription_lapse'"
        )


def downgrade() -> None:
    # Postgres does not support removing values from an enum. Downgrade is
    # intentionally a no-op; the two labels are left in place and unused if
    # the deploy reverts.
    pass
