"""add sms opt-out fields and opted_out contact status

Revision ID: 7f7df1fd5133
Revises: b33191340593
Create Date: 2026-06-11 22:00:29.653892

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f7df1fd5133'
down_revision: Union[str, None] = 'b33191340593'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "phone_numbers",
        sa.Column("sms_opted_out_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "phone_numbers",
        sa.Column("sms_opt_out_source", sa.String(), nullable=True),
    )
    op.add_column(
        "phone_numbers",
        sa.Column(
            "last_soft_stop_gate_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "circle_of_trust_members",
        sa.Column("opted_out_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ALTER TYPE ... ADD VALUE can't run in a transaction. IF NOT EXISTS
    # keeps the statement idempotent across reruns.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE contact_status_enum ADD VALUE IF NOT EXISTS 'opted_out'"
        )


def downgrade() -> None:
    # Postgres doesn't support removing enum values. We leave 'opted_out'
    # in place — application code ignores it if the deploy reverts.
    op.drop_column("circle_of_trust_members", "opted_out_at")
    op.drop_column("phone_numbers", "last_soft_stop_gate_sent_at")
    op.drop_column("phone_numbers", "sms_opt_out_source")
    op.drop_column("phone_numbers", "sms_opted_out_at")
