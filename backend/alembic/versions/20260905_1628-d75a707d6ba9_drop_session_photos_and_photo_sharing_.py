"""drop session_photos and sessions.photo_sharing_enabled

Background photo discovery — the mobile app polling the camera roll during a
session and uploading every new photo for the circle's alert page — is removed
(owner decision 2026-09-05: it never worked reliably). The `session_photos`
table only ever held those discovered photos, and `photo_sharing_enabled` only
ever gated them. The outfit photo (`sessions.outfit_photo_url`) and the profile
picture are untouched.

Single-release drop (owner decision 2026-09-05, precedent b7d3e1a2c4f5 /
commit ec3097b): during the ECS rolling swap the still-running old revision
selects the dropped column and errors on session reads until it is replaced.
Any `session-photos/` objects left in S3 are cleaned up by hand post-deploy.

Revision ID: d75a707d6ba9
Revises: f7a3d9e1c8b2
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d75a707d6ba9"
down_revision: str | None = "f7a3d9e1c8b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Indexes and foreign keys go with the table.
    op.drop_table("session_photos")
    op.drop_column("sessions", "photo_sharing_enabled")


def downgrade() -> None:
    # Mirrors bbb8c3922a29 (server default kept — it was never removed).
    op.add_column(
        "sessions",
        sa.Column(
            "photo_sharing_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # Mirrors 1870408c8f1f + the ix_session_photos_user_id index from db6c675fb517.
    op.create_table(
        "session_photos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("photo_url", sa.String(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("exif_latitude", sa.Float(), nullable=True),
        sa.Column("exif_longitude", sa.Float(), nullable=True),
        sa.Column("exif_taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_session_photos_session_id_sessions",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_session_photos_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_photos"),
    )
    op.create_index("ix_session_photos_session_id", "session_photos", ["session_id"])
    op.create_index("ix_session_photos_user_id", "session_photos", ["user_id"])
    op.create_index(
        "ix_session_photos_session_file_created",
        "session_photos",
        ["session_id", "file_created_at"],
    )
