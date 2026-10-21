"""Tests for subscription service logic."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.subscription import (
    Subscription,
)
from app.models.user import User
from app.services.subscription_service import (
    check_access,
)
from app.services.subscription_service import (
    generate_share_code as generate_referral_code,
)


def _make_user(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "phone_number": "+14155552671",
        "full_name": "Test User",
        "is_active": True,
        "phone_ownership_verified": True,
        "referral_code": "TESTCODE",
        "free_credit_end": None,
        # Phase 9 flag — defaults to honest new signup.
        "had_prior_billing_history": False,
    }
    defaults.update(kwargs)
    user = MagicMock(spec=User)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


class TestGenerateReferralCode:
    def test_length(self):
        code = generate_referral_code()
        assert len(code) == 8

    def test_alphanumeric(self):
        code = generate_referral_code()
        assert code.isalnum()
        assert code == code.upper()

    def test_unique(self):
        codes = {generate_referral_code() for _ in range(100)}
        assert len(codes) == 100


class TestCheckAccess:
    @pytest.mark.asyncio
    async def test_active_subscription_grants_access(self):
        user = _make_user()
        sub = MagicMock(spec=Subscription)
        sub.current_period_end = datetime.now(UTC) + timedelta(days=10)
        sub.plan_type = "monthly"
        sub.source = "stripe_web"
        sub.auto_renew = True

        db = AsyncMock()
        with patch(
            "app.services.subscription_service.get_active_subscription",
            return_value=sub,
        ):
            result = await check_access(db, user)

        assert result.has_access is True
        assert result.reason == "subscription"
        assert result.plan_type == "monthly"

    @pytest.mark.asyncio
    async def test_promotion_grants_access(self):
        user = _make_user()
        db = AsyncMock()

        with (
            patch(
                "app.services.subscription_service.get_active_subscription",
                return_value=None,
            ),
            patch(
                "app.services.group_plan_service.get_group_plan_for_access_check",
                return_value=None,
            ),
            patch(
                "app.services.subscription_service.is_promotion_active",
                return_value=True,
            ),
        ):
            result = await check_access(db, user)

        assert result.has_access is True
        assert result.reason == "promotion"

    @pytest.mark.asyncio
    async def test_referral_credit_grants_access(self):
        user = _make_user(
            free_credit_end=datetime.now(UTC) + timedelta(days=15),
        )
        db = AsyncMock()

        with (
            patch(
                "app.services.subscription_service.get_active_subscription",
                return_value=None,
            ),
            patch(
                "app.services.group_plan_service.get_group_plan_for_access_check",
                return_value=None,
            ),
            patch(
                "app.services.subscription_service.is_promotion_active",
                return_value=False,
            ),
        ):
            result = await check_access(db, user)

        assert result.has_access is True
        assert result.reason == "referral_credit"

    @pytest.mark.asyncio
    async def test_expired_referral_credit_no_access(self):
        user = _make_user(
            free_credit_end=datetime.now(UTC) - timedelta(days=1),
        )
        db = AsyncMock()

        with (
            patch(
                "app.services.subscription_service.get_active_subscription",
                return_value=None,
            ),
            patch(
                "app.services.group_plan_service.get_group_plan_for_access_check",
                return_value=None,
            ),
            patch(
                "app.services.subscription_service.is_promotion_active",
                return_value=False,
            ),
            patch(
                "app.services.subscription_service.get_sessions_used_count",
                return_value=5,
            ),
        ):
            result = await check_access(db, user)

        assert result.has_access is False
        assert result.reason == "none"

    @pytest.mark.asyncio
    async def test_free_trial_grants_access(self):
        user = _make_user()
        db = AsyncMock()

        with (
            patch(
                "app.services.subscription_service.get_active_subscription",
                return_value=None,
            ),
            patch(
                "app.services.group_plan_service.get_group_plan_for_access_check",
                return_value=None,
            ),
            patch(
                "app.services.subscription_service.is_promotion_active",
                return_value=False,
            ),
            patch(
                "app.services.subscription_service.get_sessions_used_count",
                return_value=0,
            ),
        ):
            result = await check_access(db, user)

        assert result.has_access is True
        assert result.reason == "free_trial"
        assert result.sessions_remaining == 1

    @pytest.mark.asyncio
    async def test_no_access_after_trial(self):
        user = _make_user()
        db = AsyncMock()

        with (
            patch(
                "app.services.subscription_service.get_active_subscription",
                return_value=None,
            ),
            patch(
                "app.services.group_plan_service.get_group_plan_for_access_check",
                return_value=None,
            ),
            patch(
                "app.services.subscription_service.is_promotion_active",
                return_value=False,
            ),
            patch(
                "app.services.subscription_service.get_sessions_used_count",
                return_value=1,
            ),
        ):
            result = await check_access(db, user)

        assert result.has_access is False
        assert result.reason == "none"
        assert result.sessions_remaining == 0

    @pytest.mark.asyncio
    async def test_access_priority_subscription_over_promotion(self):
        """Subscription should be checked first even if promotion is active."""
        user = _make_user()
        sub = MagicMock(spec=Subscription)
        sub.current_period_end = datetime.now(UTC) + timedelta(days=10)
        sub.plan_type = "annual"
        sub.source = "stripe_web"
        sub.auto_renew = True

        db = AsyncMock()
        with patch(
            "app.services.subscription_service.get_active_subscription",
            return_value=sub,
        ):
            result = await check_access(db, user)

        assert result.reason == "subscription"
        assert result.plan_type == "annual"
