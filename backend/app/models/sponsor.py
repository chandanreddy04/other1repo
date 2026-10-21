"""SponsorshipRequest tracks gift asks for fulfillment-rate analytics.

Related: app/crud/sponsor.py, app/api/v1/endpoints/sponsorship_requests.py
"""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SponsorshipRequestStatus(enum.StrEnum):
    PENDING = "pending"
    FULFILLED = "fulfilled"


class SponsorshipRequest(Base):
    __tablename__ = "sponsorship_requests"
    __table_args__ = (
        Index("ix_sr_requester_target", "requester_phone_id", "target_phone_id"),
        # At most one PENDING request per (requester, target) pair, so
        # get_pending_for_pair can't find two and the gift-webhook bookkeeping
        # can't break. Partial unique (fulfilled rows are unconstrained).
        Index(
            "ix_sr_one_pending_per_pair",
            "requester_phone_id",
            "target_phone_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        CheckConstraint(
            "status IN ('pending','fulfilled')",
            name="ck_sponsorship_requests_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    requester_phone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id")
    )
    target_phone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id")
    )
    status: Mapped[str] = mapped_column(
        String, default=SponsorshipRequestStatus.PENDING.value
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    requester_phone = relationship(
        "PhoneNumber", foreign_keys=[requester_phone_id], lazy="joined"
    )
    target_phone = relationship(
        "PhoneNumber", foreign_keys=[target_phone_id], lazy="joined"
    )
    subscription = relationship("Subscription", foreign_keys=[subscription_id])

    @property
    def requester_phone_number(self) -> str:
        return self.requester_phone.number

    @property
    def target_phone_number(self) -> str:
        return self.target_phone.number
