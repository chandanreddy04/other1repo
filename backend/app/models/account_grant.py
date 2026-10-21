"""AccountGrant — admin-managed per-account access grants.

Each enabled row grants an account (keyed by phone) lifetime complimentary
access, and OPTIONALLY a fixed OTP login code for accounts that can't receive
SMS (App Store / Play store reviewers). Empty `otp_code` → the account logs in
with the standard SMS OTP but still receives the comp grant.

Rows are created/toggled/edited live from the admin (web/admin_registry.py) —
flipping `enabled` is how the store-review bypass is time-boxed with no redeploy.
Fail-closed: no enabled row for a phone → no grant and no bypass.

Related: services/otp.py (fixed-code login path), crud/account_grant.py,
services/subscription_service.py (ensure_comp_access), web/admin_registry.py.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AccountGrant(Base):
    __tablename__ = "account_grants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # One grant per account. FK to the single phone_numbers source of truth
    # (never store the phone string directly — backend-conventions).
    phone_number_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("phone_numbers.id"),
        unique=True,
    )
    # Why the account is granted access, e.g. "App Store reviewer", "Founder friend".
    label: Mapped[str] = mapped_column(String, default="")
    # Fixed login code for accounts that can't receive SMS (store reviewers).
    # NULL/empty → the account uses the standard SMS OTP. Never logged.
    otp_code: Mapped[str | None] = mapped_column(String, nullable=True)
    # Admin on/off toggle — the time-box. Disabled → no grant, no bypass.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    phone = relationship(
        "PhoneNumber", foreign_keys=[phone_number_id], lazy="joined"
    )

    @property
    def phone_number(self) -> str:
        return self.phone.number
