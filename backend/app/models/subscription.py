import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PlanType(enum.StrEnum):
    MONTHLY = "monthly"
    ANNUAL = "annual"
    GROUP_MONTHLY = "group_monthly"
    GROUP_ANNUAL = "group_annual"
    # One-time 24h pass (Stripe mode=payment, $0.99) — the episodic rung
    # below a subscription for a single night out (flow-review 3.9).
    DAY_PASS = "day_pass"


GROUP_PLAN_TYPES = {PlanType.GROUP_MONTHLY, PlanType.GROUP_ANNUAL}


class SubscriptionStatus(enum.StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PENDING = "pending"


class SubscriptionSource(enum.StrEnum):
    STRIPE_GIFT = "stripe_gift"
    STRIPE_WEB = "stripe_web"
    REFERRAL = "referral"
    PROMOTION = "promotion"
    ADMIN = "admin"
    # Complimentary/comped access granted via the admin-managed AccountGrant
    # table (store reviewers, VIPs, comps). Distinct source so these never-billed
    # grants are excludable from real-revenue analytics.
    COMP = "comp"


class ReferralStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    EXPIRED = "expired"


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        # Enum values stored as plain strings — validate at the DB level.
        CheckConstraint(
            "plan_type IN ('monthly','annual','group_monthly','group_annual','day_pass')",
            name="ck_subscriptions_plan_type",
        ),
        CheckConstraint(
            "status IN ('active','expired','cancelled','pending')",
            name="ck_subscriptions_status",
        ),
        CheckConstraint(
            "source IN ('stripe_gift','stripe_web','referral','promotion','admin','comp')",
            name="ck_subscriptions_source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    phone_number_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id")
    )
    plan_type: Mapped[str] = mapped_column(String, default=PlanType.MONTHLY.value)
    status: Mapped[str] = mapped_column(
        String, default=SubscriptionStatus.PENDING.value
    )
    source: Mapped[str] = mapped_column(String)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, unique=True)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)
    # Idempotency stamps for the per-tick lapse-reminder fan-out so the
    # 7-day-out / 1-day-out reminders each fire exactly once per
    # subscription. NULL means "not yet sent." See
    # app/services/sub_lapse_notifications.py and the worker tick's
    # process_pending_lapse_reminders step.
    lapse_reminder_7d_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lapse_reminder_1d_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Stamped when the SMS-unsubscribe worker cancels this subscription
    # because the owner texted STOP and ignored the grace window. Used
    # by `record_opt_in` to know which subs to restore when the owner
    # later texts START — we only undo cancellations we caused, never
    # ones the user requested manually via the Stripe portal.
    cancelled_by_sms_unsubscribe_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    gifted_by_phone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    user = relationship("User", back_populates="subscriptions")
    phone = relationship("PhoneNumber", foreign_keys=[phone_number_id], lazy="joined")
    gifted_by = relationship("PhoneNumber", foreign_keys=[gifted_by_phone_id], lazy="joined")

    @property
    def phone_number(self) -> str:
        return self.phone.number

    @property
    def gifted_by_phone(self) -> str | None:
        return self.gifted_by.number if self.gifted_by else None


class Referral(Base):
    __tablename__ = "referrals"

    __table_args__ = (
        # One referral per referee — the correct uniqueness (referral_code is
        # the referrer's shared code and is intentionally NOT unique here, so
        # many people can redeem one code up to the referrer's cap).
        Index(
            "ix_referrals_one_per_referee",
            "referee_user_id",
            unique=True,
            postgresql_where=text("referee_user_id IS NOT NULL"),
        ),
        CheckConstraint(
            "status IN ('pending','completed','expired')",
            name="ck_referrals_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    referral_code: Mapped[str] = mapped_column(String, index=True)
    referee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    referee_phone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, default=ReferralStatus.PENDING.value)
    referrer_credit_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    referee_credit_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    referrer = relationship("User", foreign_keys=[referrer_user_id])
    referee = relationship("User", foreign_keys=[referee_user_id])
    referee_phone_ref = relationship("PhoneNumber", foreign_keys=[referee_phone_id], lazy="joined")

    @property
    def referee_phone(self) -> str | None:
        return self.referee_phone_ref.number if self.referee_phone_ref else None


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
