import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

STRIPE_CUSTOMER_PENDING_PREFIX = "pending:"


def is_stripe_customer_pending(value: str) -> bool:
    return value.startswith(STRIPE_CUSTOMER_PENDING_PREFIX)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    phone_number_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id")
    )
    full_name: Mapped[str | None] = mapped_column(String)  # Set after OTP verification
    profile_photo_url: Mapped[str | None] = mapped_column(String)
    expo_push_token: Mapped[str | None] = mapped_column(String, index=True)
    stripe_customer_id: Mapped[str] = mapped_column(
        String, unique=True, index=True,
        default=lambda: f"{STRIPE_CUSTOMER_PENDING_PREFIX}{uuid.uuid4()}",
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    phone_ownership_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # True when verify-otp re-attaches a Stripe Customer carrying prior
    # subscription history on a fresh-signup user_id. Used to deny the
    # free-trial branch in subscription access — a user who already had
    # paid history shouldn't earn another free session by deleting and
    # re-signing up. See docs/account-deletion-plan.md Phase 9.
    had_prior_billing_history: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Bumped to revoke all of a user's outstanding refresh tokens (e.g.
    # log-out-all / suspected compromise) without disabling the account.
    # Refresh tokens embed the value at issue time; /refresh rejects a token
    # whose `tv` is below the current version.
    token_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    share_code: Mapped[str | None] = mapped_column(String, unique=True, index=True)
    circle_invite_code: Mapped[str | None] = mapped_column(String, unique=True, index=True)
    max_referral_redemptions: Mapped[int] = mapped_column(
        Integer, default=6, server_default="6"
    )
    free_credit_end: Mapped[datetime | None] = mapped_column(
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
    # Soft-delete marker. Set when a user initiates account deletion; the
    # account enters a 30-day grace where signing back in restores it.
    # The hard-purge worker (PR adding worker_tick step) scans this column
    # to anonymize PII columns once the grace expires. See
    # docs/account-deletion-plan.md for the full state machine.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Set when the worker has acted on this user's SMS opt-out (cancelled
    # their Stripe subscription at period end and sent the confirmation
    # push). Cleared when the user texts START so a future opt-out cycle
    # gets a fresh grace clock. Idempotent marker: NULL means we haven't
    # acted yet.
    sms_unsubscribe_handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    phone = relationship("PhoneNumber", lazy="joined")
    circle_of_trust_members = relationship(
        "CircleOfTrustMember",
        foreign_keys="CircleOfTrustMember.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    # Circles where this user is the contact — DERIVED from their phone (the
    # membership's contact account is not stored). viewonly: these rows are
    # owned by the inviter (user_id), not by this contact.
    member_of_circles = relationship(
        "CircleOfTrustMember",
        primaryjoin=(
            "and_(foreign(CircleOfTrustMember.contact_phone_number_id) "
            "== User.phone_number_id, User.deleted_at.is_(None))"
        ),
        viewonly=True,
    )
    sessions = relationship(
        "Session", back_populates="user", cascade="all, delete-orphan"
    )
    sent_alerts = relationship(
        "Alert", back_populates="sent_to_user", cascade="all, delete-orphan"
    )
    circle_of_trust_settings = relationship(
        "CircleOfTrustSettings",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    subscriptions = relationship(
        "Subscription", back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def phone_number(self) -> str:
        return self.phone.number
