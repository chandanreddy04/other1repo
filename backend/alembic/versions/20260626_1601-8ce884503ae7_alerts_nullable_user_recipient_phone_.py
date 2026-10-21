"""alerts: nullable user recipient + phone recipient for SMS-only contacts

Revision ID: 8ce884503ae7
Revises: 50cd0cd753f2
Create Date: 2026-06-26 16:01:14.944410

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8ce884503ae7'
down_revision: str | None = '50cd0cd753f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SMS-only circle contacts have no account, so they could not get an Alert
    # row (sent_to_user_id was NOT NULL) — their delivery failures were silently
    # dropped, never retried, and never blocked promotion to ALERTED. Allow a
    # phone recipient as an alternative to a user recipient.
    op.alter_column("alerts", "sent_to_user_id", existing_type=sa.UUID(), nullable=True)
    op.add_column(
        "alerts", sa.Column("sent_to_phone_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        "fk_alerts_sent_to_phone_id_phone_numbers",
        "alerts",
        "phone_numbers",
        ["sent_to_phone_id"],
        ["id"],
    )
    op.create_index("ix_alerts_sent_to_phone_id", "alerts", ["sent_to_phone_id"])
    # Dedup phone-only recipients (the existing uq on sent_to_user_id treats the
    # now-NULL user id as distinct, so it doesn't cover them).
    op.create_index(
        "uq_alerts_session_phone_type",
        "alerts",
        ["session_id", "sent_to_phone_id", "alert_type"],
        unique=True,
        postgresql_where=sa.text("sent_to_phone_id IS NOT NULL"),
    )
    # Exactly one recipient kind per alert.
    op.create_check_constraint(
        "ck_alerts_exactly_one_recipient",
        "alerts",
        "(sent_to_user_id IS NULL) <> (sent_to_phone_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_alerts_exactly_one_recipient", "alerts", type_="check")
    op.drop_index("uq_alerts_session_phone_type", table_name="alerts")
    op.drop_index("ix_alerts_sent_to_phone_id", table_name="alerts")
    op.drop_constraint(
        "fk_alerts_sent_to_phone_id_phone_numbers", "alerts", type_="foreignkey"
    )
    op.drop_column("alerts", "sent_to_phone_id")
    op.alter_column(
        "alerts", "sent_to_user_id", existing_type=sa.UUID(), nullable=False
    )
