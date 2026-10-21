"""Pre-calculated reminder fire times for sessions.

The cron worker picks up unsent rows where fire_at <= now() and sends a
push to the session owner. On session extension, old reminders are
replaced with new ones for the updated deadline.

Related: crud/session_reminder.py,
         services/session_tasks.py (process_pending_reminders)
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SessionReminder(Base):
    __tablename__ = "session_reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minutes_before: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    session = relationship("Session", back_populates="reminders")

    __table_args__ = (
        Index("ix_session_reminders_pending", "fire_at", "sent_at"),
    )
