"""notification reliability phase 1

Add ALERTED to session_status_enum, retry_count + sms_provider to alerts,
session_reminders table.

Revision ID: 1f2e3d4c5b6a
Revises: 0c9b6d2cefc4
Create Date: 2026-05-10 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "1f2e3d4c5b6a"
down_revision: str | None = "0c9b6d2cefc4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add ALERTED to session_status_enum
    op.execute("ALTER TYPE session_status_enum ADD VALUE IF NOT EXISTS 'alerted'")

    # SMS provider enum + column on alerts
    op.execute("CREATE TYPE sms_provider_enum AS ENUM ('twilio', 'acs')")
    op.add_column(
        "alerts",
        sa.Column(
            "sms_provider",
            sa.Enum("twilio", "acs", name="sms_provider_enum"),
            nullable=True,
        ),
    )

    # Retry count on alerts
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

    # session_reminders table
    op.create_table(
        "session_reminders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minutes_before", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_session_reminders_pending",
        "session_reminders",
        ["fire_at", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_reminders_pending", table_name="session_reminders")
    op.drop_table("session_reminders")
    op.drop_column("alerts", "retry_count")
    op.drop_column("alerts", "sms_provider")
    op.execute("DROP TYPE sms_provider_enum")
    # Cannot drop value from enum in postgres without recreating type;
    # leaving 'alerted' in place is harmless on downgrade.
