"""Session model and status lifecycle.

Status lifecycle: ACTIVE → MISSED → ALERTED → COMPLETED (or CANCELLED).
SOS sessions set expected_return_time = now() so they are immediately
overdue — the same pipeline handles both SOS and CHECKIN types.

Related: crud/session.py, services/session_tasks.py,
         .claude/rules/domain-sessions-alerts.md
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SessionType(enum.StrEnum):
    CHECKIN = "checkin"
    SOS = "sos"


class SessionStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    MISSED = "missed"
    ALERTED = "alerted"
    CANCELLED = "cancelled"


class Session(Base):
    __tablename__ = "sessions"

    __table_args__ = (
        # The worker's every-60s overdue scan filters
        #   WHERE status='active' AND expected_return_time < cutoff.
        # sessions is never deleted, so without this it was a growing full
        # table scan; a partial index on the small ACTIVE subset keeps it fast.
        Index(
            "ix_sessions_active_overdue",
            "expected_return_time",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    session_type: Mapped[SessionType] = mapped_column(
        Enum(
            SessionType,
            name="session_type_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SessionType.CHECKIN,
        nullable=False,
    )

    expected_return_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Client's UTC offset (minutes east of UTC, e.g. -420 for PDT) captured at
    # creation so alert SMS can say "expected back by 10:30 PM" in the owner's
    # local time — times are stored UTC and the original offset is otherwise
    # lost. Nullable: older clients don't send it; copy falls back to a
    # no-time variant.
    tz_offset_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_return_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    destination: Mapped[str | None] = mapped_column(Text)
    outfit_photo_url: Mapped[str | None] = mapped_column(String)
    outfit_photo_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    location_sharing_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Battery is always captured/shared — it needs no OS permission and a dying
    # phone is safety-critical context. (There is no battery_sharing toggle.)

    status: Mapped[SessionStatus] = mapped_column(
        Enum(
            SessionStatus,
            name="session_status_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SessionStatus.ACTIVE,
        nullable=False,
    )

    # When post-session data (photos, location trail) becomes purgeable.
    # Set to completion + SESSION_DATA_RETENTION_DAYS when the session ends;
    # the owner can push it out RETENTION_EXTENSION_DAYS at a time from
    # History (flow-review E2/3.10). NULL = legacy row (treated as already
    # purgeable — matches the old purge-immediately behavior).
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # When the captured data (photos, location trail) was ACTUALLY deleted —
    # stamped inside purge_session_data(), so both the retention cleanup and
    # the admin "purge now" record it. purge_after alone can't say this: the
    # admin path deletes without touching the schedule. Surfaces render
    # "deleted on {purged_at}" from this, falling back to session end +
    # SESSION_DATA_RETENTION_DAYS for rows purged before the column existed.
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # When the session was CANCELLED (admin close-false-alarm). Deliberately
    # separate from actual_return_time, which asserts "the owner marked
    # themselves safe" — a claim an admin cannot truthfully make. This is the
    # neutral "when did it end" anchor for cancelled sessions (retention
    # floor math, purged-date fallback).
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    # NOTE: the per-session *captured* relationships below (alerts,
    # session_updates) are all surfaced on the admin session detail
    # page. If you add another kind of captured data, keep the admin in sync —
    # see the "KEEP IN SYNC" note on sessions_view in web/admin_registry.py.
    user = relationship("User", back_populates="sessions")
    alerts = relationship(
        "Alert", back_populates="session", cascade="all, delete-orphan"
    )
    session_updates = relationship(
        "SessionUpdate",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionUpdate.recorded_at",
    )
    reminders = relationship(
        "SessionReminder",
        back_populates="session",
        cascade="all, delete-orphan",
    )
