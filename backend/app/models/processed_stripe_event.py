"""Stripe webhook idempotency tracker.

Records processed Stripe event IDs to prevent duplicate handling on retries.
Related: app/api/v1/endpoints/webhooks.py
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProcessedStripeEvent(Base):
    __tablename__ = "processed_stripe_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
