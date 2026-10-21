"""Create sponsor and sponsorship_requests tables

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-03-09

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f0a1b2c3d4e5"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sponsors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "beneficiary_phone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("phone_numbers.id"),
            nullable=False,
        ),
        sa.Column(
            "sponsor_phone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("phone_numbers.id"),
            nullable=False,
        ),
        sa.Column("sponsor_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "current_subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id"),
            nullable=True,
        ),
        sa.Column("first_activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "beneficiary_phone_id",
            "sponsor_phone_id",
            name="uq_sponsors_beneficiary_sponsor",
        ),
    )
    op.create_index(
        "ix_sponsors_sponsor_phone_id", "sponsors", ["sponsor_phone_id"]
    )

    op.create_table(
        "sponsorship_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sponsor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sponsors.id"),
            nullable=False,
        ),
        sa.Column("initiated_by", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id"),
            nullable=True,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("fulfilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_sponsorship_requests_sponsor_id",
        "sponsorship_requests",
        ["sponsor_id"],
    )
    # Partial unique index: only one pending request per sponsor relationship
    op.create_index(
        "ix_sponsorship_requests_pending_unique",
        "sponsorship_requests",
        ["sponsor_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_sponsorship_requests_pending_unique", "sponsorship_requests")
    op.drop_index("ix_sponsorship_requests_sponsor_id", "sponsorship_requests")
    op.drop_table("sponsorship_requests")
    op.drop_index("ix_sponsors_sponsor_phone_id", "sponsors")
    op.drop_table("sponsors")
