"""drop sponsors replace sponsorship_requests

Revision ID: 0c9b6d2cefc4
Revises: 5f0ef10d904b
Create Date: 2026-05-09 00:11:22.723202

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0c9b6d2cefc4"
down_revision: str | None = "5f0ef10d904b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("sponsorship_requests")
    op.drop_table("sponsors")

    op.create_table(
        "sponsorship_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "requester_phone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("phone_numbers.id"),
            nullable=False,
        ),
        sa.Column(
            "target_phone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("phone_numbers.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id"),
            nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_sr_requester_target",
        "sponsorship_requests",
        ["requester_phone_id", "target_phone_id"],
    )


def downgrade() -> None:
    op.drop_table("sponsorship_requests")
    # sponsors table not restored — downgrade unsupported for this migration
