"""drop dead Alert channel columns (push/sms/retry)

Per-channel delivery + retry moved to notification_deliveries (the outbox); the
Alert is now a pure business record whose status is a rollup of its delivery
rows. The old channel-tracking columns are dead:

  - push_notification_id  (Expo ticket id — now on the delivery row)
  - sms_message_id        (provider message id — now on the delivery row)
  - sms_provider          (routed the old retry path — deliveries own routing)
  - retry_count           (alert-level retries — the reconciler owns retries)

Dropping the columns drops their dependent indexes; the sms_provider_enum type
is then unused and removed.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("alerts", "retry_count")
    op.drop_column("alerts", "sms_provider")
    op.drop_column("alerts", "sms_message_id")
    op.drop_column("alerts", "push_notification_id")
    # The enum type is now unreferenced.
    sa.Enum(name="sms_provider_enum").drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    sms_provider_enum = sa.Enum(
        "twilio", "sns", name="sms_provider_enum"
    )
    sms_provider_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "alerts",
        sa.Column("push_notification_id", sa.String(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("sms_message_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_alerts_sms_message_id", "alerts", ["sms_message_id"]
    )
    op.add_column(
        "alerts",
        sa.Column(
            "sms_provider",
            sms_provider_enum,
            nullable=True,
        ),
    )
    op.add_column(
        "alerts",
        sa.Column(
            "retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("alerts", "retry_count", server_default=None)
