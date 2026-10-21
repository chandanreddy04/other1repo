"""Tests for eager Stripe Customer creation and retry."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import is_stripe_customer_pending
from app.services.stripe_service import (
    get_or_create_stripe_customer,
    retry_pending_stripe_customers,
)
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestGetOrCreateStripeCustomer:
    async def test_returns_existing_real_id(self, db_session: AsyncSession):
        user = await create_test_user(
            db_session,
            phone_number="+16025550010",
            stripe_customer_id="cus_existing123",
        )
        result = await get_or_create_stripe_customer(db_session, user)
        assert result == "cus_existing123"

    @patch("app.services.stripe_service.stripe.Customer.create")
    async def test_creates_customer_for_pending(self, mock_create, db_session: AsyncSession):
        mock_create.return_value = MagicMock(id="cus_new456")
        user = await create_test_user(db_session, phone_number="+16025550011")
        assert is_stripe_customer_pending(user.stripe_customer_id)

        result = await get_or_create_stripe_customer(db_session, user)

        assert result == "cus_new456"
        assert user.stripe_customer_id == "cus_new456"
        mock_create.assert_called_once()

    @patch("app.services.stripe_service.stripe.Customer.create")
    async def test_stripe_failure_leaves_placeholder(self, mock_create, db_session: AsyncSession):
        import stripe

        mock_create.side_effect = stripe.StripeError("Stripe down")
        user = await create_test_user(db_session, phone_number="+16025550012")
        original = user.stripe_customer_id

        result = await get_or_create_stripe_customer(db_session, user)

        assert result == original
        assert is_stripe_customer_pending(result)

    @patch("app.services.stripe_service.stripe.Customer.create")
    async def test_idempotency_key_uses_user_id(self, mock_create, db_session: AsyncSession):
        mock_create.return_value = MagicMock(id="cus_idem789")
        user = await create_test_user(db_session, phone_number="+16025550013")

        await get_or_create_stripe_customer(db_session, user)

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["idempotency_key"] == f"customer:{user.id}"


@pytest.mark.asyncio
class TestRetryPendingStripeCustomers:
    @patch("app.services.stripe_service.stripe.Customer.create")
    async def test_resolves_pending_users(self, mock_create, db_session: AsyncSession):
        mock_create.return_value = MagicMock(id="cus_resolved")
        await create_test_user(db_session, phone_number="+16025550020")

        resolved = await retry_pending_stripe_customers(db_session)

        assert resolved >= 1

    @patch("app.services.stripe_service.stripe.Customer.create")
    async def test_skips_already_resolved(self, mock_create, db_session: AsyncSession):
        await create_test_user(
            db_session,
            phone_number="+16025550021",
            stripe_customer_id="cus_already",
        )

        resolved = await retry_pending_stripe_customers(db_session)

        assert resolved == 0
        mock_create.assert_not_called()
