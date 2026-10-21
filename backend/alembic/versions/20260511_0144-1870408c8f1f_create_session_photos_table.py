"""create session_photos table

Revision ID: 1870408c8f1f
Revises: bbb8c3922a29
Create Date: 2026-05-11 01:44:12.927105

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1870408c8f1f'
down_revision: Union[str, None] = 'bbb8c3922a29'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "session_photos",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False, index=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("photo_url", sa.String(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("exif_latitude", sa.Float(), nullable=True),
        sa.Column("exif_longitude", sa.Float(), nullable=True),
        sa.Column("exif_taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(50), nullable=True),
    )
    op.create_index("ix_session_photos_session_file_created", "session_photos", ["session_id", "file_created_at"])


def downgrade() -> None:
    op.drop_index("ix_session_photos_session_file_created", table_name="session_photos")
    op.drop_table("session_photos")
