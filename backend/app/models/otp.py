import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OTP(Base):
    __tablename__ = "otps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    phone_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    otp_code: Mapped[str] = mapped_column(String(6), nullable=False)  # 6-digit OTP

    # Security fields
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps (timezone-aware)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __init__(self, phone_number: str, otp_code: str, expires_in_minutes: int = 10):
        self.phone_number = phone_number
        self.otp_code = otp_code
        self.expires_at = datetime.now(UTC) + timedelta(minutes=expires_in_minutes)

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_expired and not self.is_used and self.attempts < 3
