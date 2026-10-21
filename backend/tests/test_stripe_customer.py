"""Tests for stripe_customer_id contract and STRIPE_WEB source."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import SubscriptionSource
from app.models.user import STRIPE_CUSTOMER_PENDING_PREFIX, is_stripe_customer_pending
from tests.helpers import create_test_user


class TestIsStripeCustomerPending:
    def test_pending_placeholder(self):
        assert is_stripe_customer_pending(f"{STRIPE_CUSTOMER_PENDING_PREFIX}abc-123") is True

    def test_real_customer_id(self):
        assert is_stripe_customer_pending("cus_abc123") is False

    def test_empty_string(self):
        assert is_stripe_customer_pending("") is False


class TestStripeCustomerIdOnUser:
    @pytest.mark.asyncio
    async def test_user_gets_pending_customer_id_by_default(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+16025550001")
        assert user.stripe_customer_id.startswith(STRIPE_CUSTOMER_PENDING_PREFIX)

    @pytest.mark.asyncio
    async def test_user_with_explicit_customer_id(self, db_session: AsyncSession):
        user = await create_test_user(
            db_session,
            phone_number="+16025550002",
            stripe_customer_id="cus_test_explicit",
        )
        assert user.stripe_customer_id == "cus_test_explicit"


class TestStripeWebSource:
    def test_stripe_web_in_enum(self):
        assert SubscriptionSource.STRIPE_WEB.value == "stripe_web"

    def test_all_sources(self):
        sources = [s.value for s in SubscriptionSource]
        assert "stripe_web" in sources
        assert "stripe_gift" in sources
