"""Add subscriptions, referrals, promotions tables and user subscription fields

Revision ID: a1b2c3d4e5f6
Revises: 2a9e2576d375
Create Date: 2026-03-07 00:01:00.000000

"""
import secrets
import string
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "2a9e2576d375"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _generate_referral_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(8))


def upgrade() -> None:
    # Create subscriptions table
    op.create_table(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("phone_number", sa.String(), nullable=False, index=True),
        sa.Column("plan_type", sa.String(), nullable=False, server_default="monthly"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("revenuecat_original_transaction_id", sa.String(), nullable=True),
        sa.Column("stripe_checkout_session_id", sa.String(), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("gifted_by_phone", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Create referrals table
    op.create_table(
        "referrals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("referrer_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("referral_code", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("referee_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("referee_phone", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("referrer_credit_applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("referee_credit_applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Create promotions table
    op.create_table(
        "promotions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # Add subscription fields to users table
    op.add_column("users", sa.Column("referral_code", sa.String(), nullable=True, unique=True))
    op.add_column("users", sa.Column("sessions_used_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("free_credit_end", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)

    # Backfill referral codes for existing users
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id FROM users WHERE referral_code IS NULL")).fetchall()
    used_codes = set()
    for user_row in users:
        code = _generate_referral_code()
        while code in used_codes:
            code = _generate_referral_code()
        used_codes.add(code)
        conn.execute(
            sa.text("UPDATE users SET referral_code = :code WHERE id = :id"),
            {"code": code, "id": user_row[0]},
        )


def downgrade() -> None:
    op.drop_index("ix_users_referral_code", table_name="users")
    op.drop_column("users", "free_credit_end")
    op.drop_column("users", "sessions_used_count")
    op.drop_column("users", "referral_code")
    op.drop_table("promotions")
    op.drop_table("referrals")
    op.drop_table("subscriptions")
