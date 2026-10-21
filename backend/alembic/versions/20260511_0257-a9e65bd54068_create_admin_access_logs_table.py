"""create admin_access_logs table

Revision ID: a9e65bd54068
Revises: db3ef145a3ed
Create Date: 2026-05-11 02:57:45.079399

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a9e65bd54068'
down_revision: Union[str, None] = 'db3ef145a3ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_access_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("entity", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_admin_access_logs_admin_created",
        "admin_access_logs",
        ["admin_user_id", "created_at"],
    )
    op.create_index(
        "ix_admin_access_logs_target_created",
        "admin_access_logs",
        ["target_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_access_logs_target_created", table_name="admin_access_logs")
    op.drop_index("ix_admin_access_logs_admin_created", table_name="admin_access_logs")
    op.drop_table("admin_access_logs")
