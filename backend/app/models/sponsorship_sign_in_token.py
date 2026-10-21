"""SponsorshipSignInToken — one-time, short-lived tokens for the
sponsorship magic-link sign-in flow.

Replaces the JWT-based sponsorship magic link (its mint/decode helpers
were removed from ``app/services/account_deletion.py`` 2026-09-27) so the SMS link can be short
(``{SHORT_DOMAIN}/s/p/<12 chars>`` instead of a ~200-char JWT query
string) and so a link can be marked used after its first successful
exchange rather than only being time-bounded.

Related: app/crud/sponsorship_sign_in_token.py (create/consume/purge),
app/web/routes_web_sponsorships.py (GET /sponsorships/portal/{token}),
app/web/short_links.py (the /s/p/{token} short link),
docs/notifications.md (S1).
"""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

TOKEN_LENGTH = 12


def generate_token() -> str:
    """A 12-char opaque, URL-safe token.

    ``secrets.token_urlsafe(9)`` encodes 9 random bytes as base64url —
    3 bytes -> 4 chars, so 9 bytes always produces exactly 12 characters
    with no padding. Drawn from the URL-safe alphabet
    (``A-Za-z0-9-_``), so it rides in a path segment with no encoding.
    """
    return secrets.token_urlsafe(9)


class SponsorshipSignInToken(Base):
    __tablename__ = "sponsorship_sign_in_tokens"

    # The token itself is the primary key: it's already a high-entropy,
    # unguessable opaque identifier, so a separate surrogate id would be
    # pure overhead.
    token: Mapped[str] = mapped_column(String(TOKEN_LENGTH), primary_key=True)
    # Phone-keyed, never a phone string column (backend-conventions.md) —
    # sponsorship management is keyed by phone, not by user account.
    phone_number_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set on first successful consume() — one-time use. NULL = unused.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    phone = relationship("PhoneNumber", foreign_keys=[phone_number_id])

    __table_args__ = (
        Index("ix_sponsorship_sign_in_tokens_phone_number_id", "phone_number_id"),
    )
