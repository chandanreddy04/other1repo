import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PhoneNumber(Base):
    __tablename__ = "phone_numbers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    number: Mapped[str] = mapped_column(String, unique=True, index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    # SMS opt-out state. Set when we observe an inbound STOP (or admin
    # action) and cleared when the number replies START. Outbound SMS
    # senders gate on this in addition to Twilio's own opt-out enforcement
    # to avoid a round-trip + so non-Twilio backends (SNS) honor it.
    sms_opted_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sms_opt_out_source: Mapped[str | None] = mapped_column(String, nullable=True)
    # 24h cooldown on the soft-stop intent gate — without this, every
    # stop-adjacent reply triggers a fresh gate SMS and we spam the user.
    last_soft_stop_gate_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
