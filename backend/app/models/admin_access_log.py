"""Audit log for admin panel access.

Every admin detail view, list view, edit, and delete action writes a row
so that admin-on-admin oversight is possible. Read-only in the admin UI.

Related: web/admin_views.py (writes rows), web/admin_registry.py (admin view)
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AdminAccessLog(Base):
    __tablename__ = "admin_access_logs"
    __table_args__ = (
        Index("ix_admin_access_logs_admin_created", "admin_user_id", "created_at"),
        Index("ix_admin_access_logs_target_created", "target_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    entity: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    admin_user = relationship("User", foreign_keys=[admin_user_id])
    target_user = relationship("User", foreign_keys=[target_user_id])
