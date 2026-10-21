import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.crud.user import crud_user
from app.models.subscription import Referral, ReferralStatus
from app.models.user import User
from app.services import sms_opt_out

logger = logging.getLogger(__name__)


class ReferralService:
    async def get_referrer_by_code(self, db: AsyncSession, code: str) -> User | None:
        """Look up user by referral code (case-insensitive)."""
        return await crud_user.get_by_share_code(db, share_code=code)

    async def has_existing_referral(self, db: AsyncSession, user_id: UUID) -> bool:
        """Check if user has already used a referral code."""
        existing = await db.execute(
            select(Referral).where(Referral.referee_user_id == user_id)
        )
        return existing.scalar_one_or_none() is not None

    async def referral_offer_for(
        self, db: AsyncSession, *, inviter: User, accepter: User
    ) -> str | None:
        """The inviter's share_code to offer the accepter a free month, or
        None when not eligible.

        Single source for the "claim a free month" gate on the Circle-invite
        lander's just-accepted state (`GET /circles/{code}?accepted=1`, the
        PRG target of `POST /circles/{code}/accept`; app/web/routes_web.py):
        eligible only when the accepter isn't the inviter, the inviter has a
        share_code to offer AND the accepter has never redeemed a referral
        (has_existing_referral). The claim itself still goes through
        `POST /htmx/referrals/claim-from-invite`, which re-checks all of it.
        """
        if inviter.id == accepter.id or not inviter.share_code:
            return None
        if await self.has_existing_referral(db, accepter.id):
            return None
        return inviter.share_code

    async def get_redemption_count(self, db: AsyncSession, referrer_id: UUID) -> int:
        """Count how many times a referrer's code has been redeemed."""
        result = await db.execute(
            select(func.count())
            .select_from(Referral)
            .where(
                Referral.referrer_user_id == referrer_id,
                Referral.status == ReferralStatus.COMPLETED,
            )
        )
        return result.scalar() or 0

    async def claim_referral(
        self, db: AsyncSession, referrer: User, referee: User, code: str
    ) -> Referral:
        """Create completed referral, apply credits to both users, and notify referrer."""
        from app.services import subscription_service

        count = await self.get_redemption_count(db, referrer.id)
        referrer_at_cap = count >= referrer.max_referral_redemptions

        referee_phone, _ = await crud_phone_number.get_or_create(
            db, number=referee.phone_number
        )
        referral = Referral(
            referrer_user_id=referrer.id,
            referral_code=code.upper(),
            referee_user_id=referee.id,
            referee_phone_id=referee_phone.id,
            status=ReferralStatus.COMPLETED,
            referrer_credit_applied=not referrer_at_cap,
            referee_credit_applied=True,
            completed_at=datetime.now(UTC),
        )
        db.add(referral)
        await db.commit()

        # Referee always gets credit
        await subscription_service.apply_referral_credit(db, referee.id)

        # Referrer only gets credit if under the cap
        if not referrer_at_cap:
            await subscription_service.apply_referral_credit(db, referrer.id)

        # Notify the referrer via SMS (only if they earned credit)
        if not referrer_at_cap:
            referee_name = referee.full_name or "Someone"
            try:
                await sms_opt_out.gated_send_sms(
                    db,
                    referrer.phone_number,
                    f"Great news! {referee_name} used your Made It Home referral. You both got a free month!",
                )
            except Exception:
                # user.id only — the phone number is PII and this reaches Bugsnag.
                logger.exception(
                    "Failed to send referral notification SMS (referrer=%s)",
                    referrer.id,
                )

        return referral


referral_service = ReferralService()
