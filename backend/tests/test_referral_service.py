"""Tests for referral service — claim_referral, get_referrer_by_code, has_existing_referral."""

import secrets
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Referral, ReferralStatus
from app.models.user import User
from app.services.referral import referral_service
from tests.helpers import create_test_user


async def _create_user(
    db: AsyncSession, phone: str, name: str = "Test User"
) -> User:
    user = await create_test_user(db, phone_number=phone, full_name=name)
    if not user.share_code:
        user.share_code = secrets.token_hex(4).upper()
        await db.commit()
        await db.refresh(user)
    return user


@pytest.mark.asyncio
class TestGetReferrerByCode:
    async def test_existing_code(self, db_session: AsyncSession):
        user = await _create_user(db_session, "+14155580001")
        result = await referral_service.get_referrer_by_code(
            db_session, user.share_code
        )
        assert result is not None
        assert result.id == user.id

    async def test_nonexistent_code(self, db_session: AsyncSession):
        result = await referral_service.get_referrer_by_code(
            db_session, "ZZZZZZZZ"
        )
        assert result is None


@pytest.mark.asyncio
class TestHasExistingReferral:
    async def test_no_referral(self, db_session: AsyncSession):
        user = await _create_user(db_session, "+14155580010")
        assert await referral_service.has_existing_referral(db_session, user.id) is False

    async def test_with_referral(self, db_session: AsyncSession):
        referrer = await _create_user(db_session, "+14155580011")
        referee = await _create_user(db_session, "+14155580012")
        referral = Referral(
            referrer_user_id=referrer.id,
            referral_code=referrer.share_code,
            referee_user_id=referee.id,
            referee_phone_id=referee.phone_number_id,
            status=ReferralStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
        db_session.add(referral)
        await db_session.commit()

        assert await referral_service.has_existing_referral(db_session, referee.id) is True


@pytest.mark.asyncio
class TestGetRedemptionCount:
    async def test_zero_redemptions(self, db_session: AsyncSession):
        user = await _create_user(db_session, "+14155580020")
        count = await referral_service.get_redemption_count(db_session, user.id)
        assert count == 0

    async def test_with_redemptions(self, db_session: AsyncSession):
        referrer = await _create_user(db_session, "+14155580021")
        for i in range(3):
            referee = await _create_user(db_session, f"+1415558003{i}")
            referral = Referral(
                referrer_user_id=referrer.id,
                referral_code=f"{referrer.share_code}_{i}",
                referee_user_id=referee.id,
                referee_phone_id=referee.phone_number_id,
                status=ReferralStatus.COMPLETED,
                completed_at=datetime.now(UTC),
            )
            db_session.add(referral)
        await db_session.commit()

        count = await referral_service.get_redemption_count(db_session, referrer.id)
        assert count == 3


@pytest.mark.asyncio
class TestClaimReferral:
    @patch("app.services.referral.sms_opt_out")
    @patch("app.services.subscription_service.apply_referral_credit", new_callable=AsyncMock)
    async def test_claim_referral_success(
        self, mock_credit, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = AsyncMock()
        referrer = await _create_user(db_session, "+14155580040", "Referrer")
        referee = await _create_user(db_session, "+14155580041", "Referee")

        referral = await referral_service.claim_referral(
            db_session, referrer, referee, referrer.share_code
        )

        assert referral.status == ReferralStatus.COMPLETED
        assert referral.referrer_credit_applied is True
        assert referral.referee_credit_applied is True
        assert mock_credit.call_count == 2
        mock_sms.gated_send_sms.assert_called_once()

    @patch("app.services.referral.sms_opt_out")
    @patch("app.services.subscription_service.apply_referral_credit", new_callable=AsyncMock)
    async def test_claim_referral_at_cap(
        self, mock_credit, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = AsyncMock()
        referrer = await _create_user(db_session, "+14155580042", "Capped Referrer")
        referrer.max_referral_redemptions = 1

        cap_referee = await _create_user(db_session, "+14155580043")
        db_session.add(Referral(
            referrer_user_id=referrer.id,
            referral_code=f"{referrer.share_code}_cap",
            referee_user_id=cap_referee.id,
            referee_phone_id=cap_referee.phone_number_id,
            status=ReferralStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        ))
        await db_session.commit()

        new_referee = await _create_user(db_session, "+14155580044", "New Ref")
        referral = await referral_service.claim_referral(
            db_session, referrer, new_referee, referrer.share_code
        )

        assert referral.referrer_credit_applied is False
        assert mock_credit.call_count == 1
        mock_sms.gated_send_sms.assert_not_called()

    @patch("app.services.referral.sms_opt_out")
    @patch("app.services.subscription_service.apply_referral_credit", new_callable=AsyncMock)
    async def test_claim_referral_sms_failure_ignored(
        self, mock_credit, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = AsyncMock(side_effect=RuntimeError("SMS failed"))
        referrer = await _create_user(db_session, "+14155580045", "Referrer")
        referee = await _create_user(db_session, "+14155580046", "Referee")

        referral = await referral_service.claim_referral(
            db_session, referrer, referee, referrer.share_code
        )
        assert referral.status == ReferralStatus.COMPLETED
