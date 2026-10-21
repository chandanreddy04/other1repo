"""notification_deliveries outbox table

One row per (recipient, channel, kind); the worker reconciler drives each to a
terminal delivery state. Additive — no backfill (pre-prod, no in-flight rows).

Revision ID: c3d4e5f6a7b8
Revises: a1c2e3f4b5d6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "a1c2e3f4b5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KIND = sa.Enum(
    "circle_alert",
    "circle_renudge",
    "owner_reminder",
    "owner_deadline",
    "session_expired_owner",
    "circle_alerted",
    "all_clear",
    "alert_claimed",
    "contact_unreachable",
    "contact_opted_out",
    "circle_emptied",
    "circle_emptied_mid_session",
    "data_deleted",
    name="notification_kind_enum",
)
_CHANNEL = sa.Enum("push", "sms", name="notification_channel_enum")
_STATUS = sa.Enum(
    "pending",
    "sent",
    "delivered",
    "failed",
    "refused",
    "exhausted",
    "superseded",
    name="notification_delivery_status_enum",
)


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("kind", _KIND, nullable=False),
        sa.Column("channel", _CHANNEL, nullable=False),
        sa.Column("recipient_user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "recipient_phone_id", sa.UUID(), sa.ForeignKey("phone_numbers.id"), nullable=True
        ),
        sa.Column("session_id", sa.UUID(), sa.ForeignKey("sessions.id"), nullable=True),
        sa.Column("alert_id", sa.UUID(), sa.ForeignKey("alerts.id"), nullable=True),
        sa.Column(
            "status", _STATUS, nullable=False, server_default="pending"
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=20), nullable=True),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("dedupe_key", name="uq_nd_dedupe"),
        sa.CheckConstraint(
            "(recipient_user_id IS NULL) <> (recipient_phone_id IS NULL)",
            name="ck_nd_exactly_one_recipient",
        ),
        sa.CheckConstraint(
            "channel <> 'push' OR recipient_user_id IS NOT NULL",
            name="ck_nd_push_needs_user",
        ),
    )
    op.create_index(
        "ix_nd_due",
        "notification_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending','failed')"),
    )
    op.create_index(
        "ix_nd_receipts",
        "notification_deliveries",
        ["sent_at"],
        postgresql_where=sa.text("status = 'sent'"),
    )
    op.create_index(
        "ix_nd_provider_msg", "notification_deliveries", ["provider_message_id"]
    )
    op.create_index("ix_nd_session", "notification_deliveries", ["session_id"])
    op.create_index("ix_nd_alert", "notification_deliveries", ["alert_id"])
    op.create_index(
        "ix_notification_deliveries_recipient_user_id",
        "notification_deliveries",
        ["recipient_user_id"],
    )
    op.create_index(
        "ix_notification_deliveries_recipient_phone_id",
        "notification_deliveries",
        ["recipient_phone_id"],
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    _STATUS.drop(op.get_bind(), checkfirst=True)
    _CHANNEL.drop(op.get_bind(), checkfirst=True)
    _KIND.drop(op.get_bind(), checkfirst=True)
