"""NotificationDelivery — the delivery outbox.

One row per (recipient, channel, notification kind). A row is written in the
SAME transaction as the state change that owes the notification (SOS creation,
MISSED promotion, completion, claim), and the worker's reconciler drives it to
exactly one terminal state: delivered / exhausted / superseded / refused. This
is the durable record that guarantees an owed notification is never
"attempted once and forgotten" — delivery truth comes from provider receipts
(Twilio/SNS webhooks, Expo receipts), not from "the HTTP call returned".

`dedupe_key` makes every enqueue idempotent (ON CONFLICT DO NOTHING), so
re-running an enqueue path — or two overlapping ticks — can't double-send.

`claimed_at` is the claim used by the dispatcher (crud.claim / get_due,
services/notification_outbox.send_due_deliveries) to make sure exactly one
caller sends a given row even when `send_due_deliveries` is invoked from more
than one place at once (the worker tick vs. an inline request-path dispatch
via `enqueue_and_send`/`process_overdue`) — see those modules for the
compare-and-swap + TTL details.

Related: crud/notification_delivery.py, services/notification_outbox.py,
         services/notification_policy.py, models/alert.py (the business object).
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationKind(enum.StrEnum):
    CIRCLE_ALERT = "circle_alert"
    CIRCLE_RENUDGE = "circle_renudge"
    OWNER_REMINDER = "owner_reminder"  # retired 2026-09: no producer; DB enum value kept
    OWNER_DEADLINE = "owner_deadline"
    SESSION_EXPIRED_OWNER = "session_expired_owner"
    CIRCLE_ALERTED = "circle_alerted"
    ALL_CLEAR = "all_clear"
    ALERT_ACKNOWLEDGED = "alert_acknowledged"
    CONTACT_UNREACHABLE = "contact_unreachable"
    CONTACT_OPTED_OUT = "contact_opted_out"
    CONTACT_LEFT = "contact_left"
    CIRCLE_EMPTIED = "circle_emptied"
    CIRCLE_EMPTIED_MID_SESSION = "circle_emptied_mid_session"
    DATA_DELETED = "data_deleted"
    GROUP_PLAN_GRACE = "group_plan_grace"
    SUBSCRIPTION_LAPSE = "subscription_lapse"
    ACCOUNT_HOLDER_UNSUBSCRIBED = "account_holder_unsubscribed"
    ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED = "account_holder_subscription_cancelled"


class DeliveryChannel(enum.StrEnum):
    PUSH = "push"
    SMS = "sms"


class DeliveryStatus(enum.StrEnum):
    PENDING = "pending"  # enqueued, not yet sent
    SENT = "sent"  # provider accepted; awaiting receipt (or terminal for non-receipt kinds)
    DELIVERED = "delivered"  # receipt confirmed
    FAILED = "failed"  # a send attempt failed; will retry per policy
    REFUSED = "refused"  # server-side refusal (no channel, opted out) — terminal, no retry
    EXHAUSTED = "exhausted"  # retries used up — terminal, escalates for circle kinds
    SUPERSEDED = "superseded"  # made moot (claimed, extended, resolved) — terminal


# Terminal states no reconciler should ever re-attempt.
TERMINAL_STATUSES = frozenset(
    {
        DeliveryStatus.DELIVERED,
        DeliveryStatus.REFUSED,
        DeliveryStatus.EXHAUSTED,
        DeliveryStatus.SUPERSEDED,
    }
)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    __table_args__ = (
        # Idempotent enqueue: the deterministic key makes re-running any enqueue
        # path (or two overlapping ticks) a no-op via ON CONFLICT DO NOTHING.
        UniqueConstraint("dedupe_key", name="uq_nd_dedupe"),
        # Exactly-one-recipient like Alert (users OR phone_numbers).
        CheckConstraint(
            "(recipient_user_id IS NULL) <> (recipient_phone_id IS NULL)",
            name="ck_nd_exactly_one_recipient",
        ),
        # Push needs an account (the push token lives on users).
        CheckConstraint(
            "channel <> 'push' OR recipient_user_id IS NOT NULL",
            name="ck_nd_push_needs_user",
        ),
        # The reconciler's due-scan: pending/failed rows ordered by next_attempt_at.
        Index(
            "ix_nd_due",
            "next_attempt_at",
            postgresql_where=text("status IN ('pending','failed')"),
        ),
        # Receipt-poll / receipt-timeout scan over sent rows.
        Index(
            "ix_nd_receipts",
            "sent_at",
            postgresql_where=text("status = 'sent'"),
        ),
        Index("ix_nd_provider_msg", "provider_message_id"),
        Index("ix_nd_session", "session_id"),
        Index("ix_nd_alert", "alert_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)

    kind: Mapped[NotificationKind] = mapped_column(
        Enum(
            NotificationKind,
            name="notification_kind_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    channel: Mapped[DeliveryChannel] = mapped_column(
        Enum(
            DeliveryChannel,
            name="notification_channel_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    recipient_phone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id"), nullable=True, index=True
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id"), nullable=True
    )

    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(
            DeliveryStatus,
            name="notification_delivery_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=DeliveryStatus.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Set by crud.claim() right before dispatch, cleared by every terminal/backoff
    # update. A row with a fresh (< CLAIM_TTL old) claimed_at is excluded from
    # get_due, so a second dispatcher can't pick it up mid-send; a stale claim
    # (crashed dispatcher) ages out and the row becomes claimable again.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    provider: Mapped[str | None] = mapped_column(String(20))  # twilio | sns | expo
    provider_message_id: Mapped[str | None] = mapped_column(String)

    # Content is a point-in-time SNAPSHOT (local time, battery, destination are
    # enqueue-time facts that would drift if re-derived at send). Same rationale
    # as the denormalized Alert.message column.
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON)

    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
