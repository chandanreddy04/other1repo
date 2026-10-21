"""CRUD for SponsorshipSignInToken — the one-time sign-in tokens behind the
sponsorship magic-link short link (GET /sponsorships/portal/{token} checks
them read-only; POST /sponsorships/portal/{token} consumes them).

Not a CRUDBase subclass: the model's primary key is the token string
itself, not an ``id`` column, so the generic get/remove-by-id helpers
don't apply here.

Related: app/models/sponsorship_sign_in_token.py, app/web/routes_web_
sponsorships.py, app/services/session_tasks.py (hourly purge).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phone_number import PhoneNumber
from app.models.sponsorship_sign_in_token import (
    SponsorshipSignInToken,
    generate_token,
)
from app.services.account_deletion import SPONSORSHIP_TOKEN_TTL_MINUTES


class CRUDSponsorshipSignInToken:
    async def create_for_phone(
        self, db: AsyncSession, *, phone_number_id: uuid.UUID
    ) -> SponsorshipSignInToken:
        """Mint a fresh one-time sign-in token for a phone.

        TTL is SPONSORSHIP_TOKEN_TTL_MINUTES (10 min) so the SMS wording
        ("expires in 10 minutes") stays accurate.

        No retry on a primary-key collision, deliberately: the token carries
        72 random bits and the table only ever holds ~10 minutes' worth of
        live rows (+ up to an hour of expired ones before the hourly purge),
        so a collision is ~rows / 2**72 per insert — never in practice. If it
        ever happened the IntegrityError surfaces as a reported 500 and the
        sponsor simply resubmits the form.
        """
        token = SponsorshipSignInToken(
            token=generate_token(),
            phone_number_id=phone_number_id,
            expires_at=datetime.now(UTC)
            + timedelta(minutes=SPONSORSHIP_TOKEN_TTL_MINUTES),
        )
        db.add(token)
        await db.commit()
        await db.refresh(token)
        return token

    async def is_redeemable(self, db: AsyncSession, *, token: str) -> bool:
        """Read-only check that a token exists, is unexpired and unused —
        what ``consume()`` would accept right now — WITHOUT stamping
        ``used_at``. Backs ``GET /sponsorships/portal/{token}``, which link
        previewers fetch on their own: a GET must never burn the one-time
        token; only the page's POST consumes it.
        """
        result = await db.execute(
            select(SponsorshipSignInToken.token).where(
                SponsorshipSignInToken.token == token,
                SponsorshipSignInToken.used_at.is_(None),
                SponsorshipSignInToken.expires_at > datetime.now(UTC),
            )
        )
        return result.scalar_one_or_none() is not None

    async def consume(
        self, db: AsyncSession, *, token: str
    ) -> PhoneNumber | None:
        """Redeem a one-time sign-in token: must exist, be unexpired, and
        be unused. Returns the associated PhoneNumber, or None for any
        unknown/expired/already-used token — the caller can't (and
        shouldn't) distinguish those cases from the response.

        Atomic: ONE ``UPDATE … WHERE token=:t AND used_at IS NULL AND
        expires_at > now RETURNING phone_number_id`` (same pattern as
        ``crud_session.claim_for_processing``), so two concurrent clicks on
        the same link can't both win — a read-then-write would let both
        see ``used_at IS NULL`` before either stamps it.

        Never logs the token itself (security.md). Constant-time comparison
        is unnecessary: this is an indexed DB lookup, not a string
        comparison against a secret held in the process.
        """
        now = datetime.now(UTC)
        result = await db.execute(
            update(SponsorshipSignInToken)
            .where(
                SponsorshipSignInToken.token == token,
                SponsorshipSignInToken.used_at.is_(None),
                SponsorshipSignInToken.expires_at > now,
            )
            .values(used_at=now)
            .returning(SponsorshipSignInToken.phone_number_id)
        )
        phone_number_id = result.scalar_one_or_none()
        await db.commit()
        if phone_number_id is None:
            return None
        return await db.get(PhoneNumber, phone_number_id)

    async def release(self, db: AsyncSession, *, token: str) -> None:
        """Undo a consume() whose exchange failed downstream (the Stripe
        portal session couldn't be created), so a provider blip doesn't
        burn the sponsor's one link. Expiry still applies — a released
        token is only usable again until its original ``expires_at``."""
        await db.execute(
            update(SponsorshipSignInToken)
            .where(SponsorshipSignInToken.token == token)
            .values(used_at=None)
        )
        await db.commit()

    async def purge_expired(self, db: AsyncSession) -> int:
        """Delete every token past its expiry (used or not) — called from
        the hourly worker-tick cleanup (session_tasks.cleanup_expired_data)."""
        result = await db.execute(
            delete(SponsorshipSignInToken).where(
                SponsorshipSignInToken.expires_at <= datetime.now(UTC)
            )
        )
        await db.commit()
        return result.rowcount or 0


crud_sponsorship_sign_in_token = CRUDSponsorshipSignInToken()
