"""Add notification_deliveries.claimed_at (outbox dispatch claim)

Adds the nullable claim timestamp used by crud_notification_delivery.claim /
get_due (app/services/notification_outbox.send_due_deliveries) to guarantee
exactly one dispatcher sends a given row even when send_due_deliveries is
invoked from more than one place concurrently (the worker tick vs. an inline
request-path dispatch via enqueue_and_send/process_overdue, which run outside
the worker's advisory lock). No new index: the existing partial index
ix_nd_due already narrows the due-scan to a small (status, next_attempt_at)
candidate set, so filtering that further on claimed_at needs no index of its
own.

Revision ID: fe2c7404af02
Revises: a2b3c4d5e6f7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "fe2c7404af02"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification_deliveries",
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notification_deliveries", "claimed_at")
