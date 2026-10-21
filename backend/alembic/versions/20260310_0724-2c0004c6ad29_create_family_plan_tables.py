"""create_family_plan_tables

Revision ID: 2c0004c6ad29
Revises: f0a1b2c3d4e5
Create Date: 2026-03-10 07:24:49.939471

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '2c0004c6ad29'
down_revision: Union[str, None] = 'f0a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "family_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subscription_id", UUID(as_uuid=True), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("invite_code", sa.String, nullable=False),
        sa.Column("max_members", sa.Integer, nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("subscription_id", name="uq_family_plans_subscription"),
        sa.UniqueConstraint("invite_code", name="uq_family_plans_invite_code"),
    )

    op.create_table(
        "family_plan_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("family_plan_id", UUID(as_uuid=True), sa.ForeignKey("family_plans.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("family_plan_id", "user_id", name="uq_fpm_plan_user"),
    )

    # Partial unique index: one active plan per user
    op.create_index(
        "ix_fpm_one_active_per_user",
        "family_plan_members",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("left_at IS NULL"),
    )

    # Composite index for listing active members
    op.create_index(
        "ix_fpm_plan_left",
        "family_plan_members",
        ["family_plan_id", "left_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_fpm_plan_left", table_name="family_plan_members")
    op.drop_index("ix_fpm_one_active_per_user", table_name="family_plan_members")
    op.drop_table("family_plan_members")
    op.drop_table("family_plans")
