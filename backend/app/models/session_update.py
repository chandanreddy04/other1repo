"""Periodic device state snapshots during active sessions.

Stores location and/or battery readings sent by the mobile app every 5 minutes
(or every 30 seconds when escalated after an alert triggers). A row may be
location-only, battery-only, or both: battery has no permission and is always
capturable, so an opportunistic heartbeat can report a battery reading even when
location is off (coords null). See models/__init__.py, which derives the
session's last-known location from the latest COORD-bearing row and its battery
from the latest BATTERY-bearing row, so a battery-only ping never blanks the pin.

Related: crud/session.py, services/session_tasks.py (cleanup),
         api/v1/endpoints/sessions.py (update + history endpoints)
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SessionUpdate(Base):
    __tablename__ = "session_updates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False, index=True
    )

    # Nullable: a battery-only heartbeat carries no coordinates.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_state: Mapped[str | None] = mapped_column(String(20), nullable=True)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    session = relationship("Session", back_populates="session_updates")
