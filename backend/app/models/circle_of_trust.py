import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ContactStatus(enum.StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    # Contact texted STOP (or admin set them inactive via opt-out path).
    # Reversible in-place via inbound START (record_opt_in) — distinct from
    # REMOVED, which is a deliberate relationship end.
    OPTED_OUT = "opted_out"
    # Declined, left, or owner-removed. Row is preserved (not deleted) so
    # re-adding revives it to PENDING rather than minting a new identity.
    REMOVED = "removed"


class CircleOfTrustMember(Base):
    __tablename__ = "circle_of_trust_members"

    # Identity is (user_id, contact_phone_number_id): a relationship is one
    # durable row per (inviter, contact phone), status-driven. The contact's
    # app account is DERIVED from the phone — never stored — so there is no
    # snapshot column to drift.
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "contact_phone_number_id",
            name="uq_cot_members_user_phone",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )  # The inviter / circle owner
    contact_phone_number_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id")
    )  # Identity of the contact — always set

    # The inviter's own label for this contact ("Mom"). Optional: falls back to
    # the contact's account name when they're an app user (see display_name).
    # Required at the UX layer for non-app contacts, who have no account name.
    nickname: Mapped[str | None] = mapped_column(String)
    phone_contact_id: Mapped[str | None] = mapped_column(
        String
    )  # ID from phone contacts for import tracking

    status: Mapped[ContactStatus] = mapped_column(
        Enum(
            ContactStatus,
            name="contact_status_enum",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=ContactStatus.PENDING,
    )

    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # SMS invitation fields
    sms_invitation_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_invitation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    sms_message_id: Mapped[str | None] = mapped_column(
        String
    )  # Twilio message ID for tracking

    # Nudge tracking
    last_nudged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Stamped when status flips to OPTED_OUT / REMOVED so the timeline is
    # reconstructable without a separate audit table.
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    user = relationship(
        "User", foreign_keys=[user_id], back_populates="circle_of_trust_members"
    )
    contact_phone_ref = relationship("PhoneNumber", lazy="joined")
    # The contact's app account, DERIVED from the phone: the single active
    # (non-deleted) user who owns contact_phone_number_id. Guaranteed at most
    # one by the partial unique index on users(phone_number_id) WHERE
    # deleted_at IS NULL. viewonly — never written.
    contact_user = relationship(
        "User",
        primaryjoin=(
            "and_(foreign(CircleOfTrustMember.contact_phone_number_id) "
            "== User.phone_number_id, User.deleted_at.is_(None))"
        ),
        viewonly=True,
        uselist=False,
        lazy="joined",
    )

    @property
    def contact_phone_number(self) -> str | None:
        return self.contact_phone_ref.number if self.contact_phone_ref else None

    @property
    def is_app_user(self) -> bool:
        """Whether the contact has an app account (owns their phone)."""
        return self.contact_user is not None

    @property
    def contact_full_name(self) -> str | None:
        """The contact's own account name, if they're an app user."""
        return self.contact_user.full_name if self.contact_user else None

    @property
    def display_name(self) -> str | None:
        """The inviter's nickname, falling back to the contact's account name."""
        if self.nickname:
            return self.nickname
        return self.contact_full_name
