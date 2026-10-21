"""perf indexes: overdue scan, user FKs, alert sms_message_id

Revision ID: db6c675fb517
Revises: 8e4f8ec5df12
Create Date: 2026-06-26 15:31:05.749920

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'db6c675fb517'
down_revision: str | None = '8e4f8ec5df12'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The worker scans for overdue sessions every 60s:
    #   WHERE status='active' AND expected_return_time < cutoff
    # `sessions` had only a PK and is never deleted, so this was a growing
    # full table scan. A partial index on the tiny ACTIVE subset keeps it O(log n).
    op.create_index(
        "ix_sessions_active_overdue",
        "sessions",
        ["expected_return_time"],
        postgresql_where=sa.text("status = 'active'"),
    )
    # Delivery webhooks (Twilio/SNS) look up the alert by sms_message_id.
    op.create_index("ix_alerts_sms_message_id", "alerts", ["sms_message_id"])

    # Postgres does not auto-index FK columns. These back the common
    # "my X" lookups and the ON DELETE cascades.
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_alerts_sent_to_user_id", "alerts", ["sent_to_user_id"])
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index(
        "ix_family_plan_members_user_id", "family_plan_members", ["user_id"]
    )
    op.create_index("ix_session_photos_user_id", "session_photos", ["user_id"])

    # Redundant: a UNIQUE index already covers stripe_subscription_id.
    op.drop_index(
        "ix_subscriptions_stripe_subscription_id", table_name="subscriptions"
    )


def downgrade() -> None:
    op.create_index(
        "ix_subscriptions_stripe_subscription_id",
        "subscriptions",
        ["stripe_subscription_id"],
    )
    op.drop_index("ix_session_photos_user_id", table_name="session_photos")
    op.drop_index("ix_family_plan_members_user_id", table_name="family_plan_members")
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_index("ix_alerts_sent_to_user_id", table_name="alerts")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_alerts_sms_message_id", table_name="alerts")
    op.drop_index("ix_sessions_active_overdue", table_name="sessions")
