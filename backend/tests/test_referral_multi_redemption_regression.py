"""Regression for payments H1: a referral code must be redeemable by many people.

referrals.referral_code stored the referrer's shared code (same value for every
redeemer). It used to be UNIQUE, so the 2nd person to use any code hit an
IntegrityError (500) and max_referral_redemptions was unreachable. The code is
now non-unique; uniqueness is "one referral per referee" instead.

Related: app/models/subscription.py (Referral), app/services/referral.py,
         alembic migration 50cd0cd753f2.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Referral
from app.services.referral import referral_service
from tests.helpers import create_test_user


@pytest.mark.asyncio
async def test_two_referees_can_redeem_the_same_code(db_session: AsyncSession):
    referrer = await create_test_user(db_session, phone_number="+14155563001")
    code = "FRIEND01"  # the referrer's shared code — same for every redeemer
    referee_a = await create_test_user(db_session, phone_number="+14155563002")
    referee_b = await create_test_user(db_session, phone_number="+14155563003")

    r1 = await referral_service.claim_referral(db_session, referrer, referee_a, code)
    # The 2nd redemption used to raise IntegrityError on the unique code.
    r2 = await referral_service.claim_referral(db_session, referrer, referee_b, code)

    assert r1.id != r2.id
    assert r1.referral_code == r2.referral_code  # same referrer code, allowed now
    total = await db_session.scalar(
        select(func.count())
        .select_from(Referral)
        .where(Referral.referrer_user_id == referrer.id)
    )
    assert total == 2
