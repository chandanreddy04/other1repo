"""Alert model — the business record of a notification to a circle member.

Every alert has a session_id; alerts go TO circle members ABOUT the session
owner. Per-channel delivery + retry live in notification_deliveries (the outbox);
Alert.status is a rollup of those delivery rows (rollup_alert_status).

Related: models/notification_delivery.py, crud/alert.py,
         services/notification_outbox.py
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AlertType(enum.StrEnum):
    MISSED_SESSION = "missed_session"
    REMINDER = "reminder"
    PANIC = "panic"


class AlertStatus(enum.StrEnum):
    SENT = "sent"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"
    RESOLVED = "resolved"


class SMSProvider(enum.StrEnum):
    TWILIO = "twilio"
    SNS = "sns"


class Alert(Base):
    __tablename__ = "alerts"

    __table_args__ = (
        # One alert per (session, recipient, type). Defense-in-depth against
        # duplicate dispatch when two overlapping worker ticks process the same
        # MISSED session concurrently — the MISSED-retry path has no atomic
        # claim (unlike ACTIVE->MISSED), so it relies on this constraint plus
        # the run_tick_with_lock advisory lock. alert_type is part of the key so
        # a future circle REMINDER follow-up can coexist with the initial
        # MISSED_SESSION/PANIC alert to the same recipient.
        UniqueConstraint(
            "session_id",
            "sent_to_user_id",
            "alert_type",
            name="uq_alerts_session_recipient_type",
        ),
        # Same dedup for phone-only recipients (sent_to_user_id is NULL for
        # those, so the constraint above — where NULLs are distinct — doesn't
        # cover them). Partial unique on the phone recipient instead.
        Index(
            "uq_alerts_session_phone_type",
            "session_id",
            "sent_to_phone_id",
            "alert_type",
            unique=True,
            postgresql_where=text("sent_to_phone_id IS NOT NULL"),
        ),
        # Exactly one recipient kind per alert.
        CheckConstraint(
            "(sent_to_user_id IS NULL) <> (sent_to_phone_id IS NULL)",
            name="ck_alerts_exactly_one_recipient",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    # Exactly one of sent_to_user_id / sent_to_phone_id is set (CheckConstraint
    # above). Phone-only recipients are SMS-only circle contacts with no account.
    sent_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    sent_to_phone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id"), nullable=True, index=True
    )

    alert_type: Mapped[AlertType] = mapped_column(
        Enum(
            AlertType,
            name="alert_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    status: Mapped[AlertStatus] = mapped_column(
        Enum(
            AlertStatus,
            name="alert_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=AlertStatus.SENT,
        nullable=False,
    )

    message: Mapped[str | None] = mapped_column(Text)

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Rollup of the alert's notification_deliveries: DELIVERED when any delivery
    # is delivered, FAILED when all are terminal-failed (see rollup_alert_status).
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # Relationships
    session = relationship("Session", back_populates="alerts")
    sent_to_user = relationship("User", back_populates="sent_alerts")
    sent_to_phone = relationship("PhoneNumber")
