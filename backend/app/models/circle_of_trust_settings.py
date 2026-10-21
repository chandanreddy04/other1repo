import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CircleOfTrustSettings(Base):
    __tablename__ = "circle_of_trust_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, unique=True
    )

    # Settings
    max_contacts: Mapped[int] = mapped_column(
        Integer, default=3, nullable=False
    )  # Maximum number of trusted contacts
    auto_import_contacts: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    sms_invitations_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    notification_preferences: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Flexible settings storage

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    user = relationship("User", back_populates="circle_of_trust_settings")
