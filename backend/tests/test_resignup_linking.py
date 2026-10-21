"""Tests for Phase 9 re-signup linking and free-trial denial.

Verifies:
- find_existing_customer_by_phone returns the right customer / None
- customer_has_subscription_history reads the Stripe sub-list
- verify-otp re-attaches an existing customer on fresh signup, stamps
  had_prior_billing_history when the matched customer has prior subs
- check_access denies the free-trial branch when the flag is set
"""
from unittest.mock import patch

import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import subscription_service
from app.services.stripe_service import (
    customer_has_subscription_history,
    find_existing_customer_by_phone,
)
from tests.helpers import create_test_user


class TestFindExistingCustomer:
    @patch("app.services.stripe_service.stripe.Customer.search")
    def test_returns_first_match(self, mock_search):
        mock_search.return_value = {"data": [{"id": "cus_old_xyz"}]}
        match = find_existing_customer_by_phone("+14155553333")
        assert match["id"] == "cus_old_xyz"
        mock_search.assert_called_once()
        assert "+14155553333" in mock_search.call_args.kwargs["query"]

    @patch("app.services.stripe_service.stripe.Customer.search")
    def test_no_match_returns_none(self, mock_search):
        mock_search.return_value = {"data": []}
        assert find_existing_customer_by_phone("+14155554444") is None

    @patch("app.services.stripe_service.stripe.Customer.search")
    def test_stripe_error_returns_none(self, mock_search):
        """A Stripe outage must not block signup — fall back to None
        and let get_or_create_stripe_customer create a fresh one."""
        mock_search.side_effect = stripe.StripeError("down")
        assert find_existing_customer_by_phone("+14155555555") is None


class TestCustomerHasSubHistory:
    @patch("app.services.stripe_service.stripe.Subscription.list")
    def test_true_when_any_sub_exists(self, mock_list):
        mock_list.return_value = {"data": [{"id": "sub_xyz"}]}
        assert customer_has_subscription_history("cus_x") is True
        mock_list.assert_called_once()
        # We must check status="all" so cancelled subs still count.
        assert mock_list.call_args.kwargs["status"] == "all"

    @patch("app.services.stripe_service.stripe.Subscription.list")
    def test_false_when_no_subs(self, mock_list):
        mock_list.return_value = {"data": []}
        assert customer_has_subscription_history("cus_x") is False

    @patch("app.services.stripe_service.stripe.Subscription.list")
    def test_stripe_error_false(self, mock_list):
        """A Stripe outage at this check must NOT accidentally deny
        access to a legitimate brand-new user — fall back to false."""
        mock_list.side_effect = stripe.StripeError("down")
        assert customer_has_subscription_history("cus_x") is False


@pytest.mark.asyncio
class TestVerifyOtpResignupReattachment:
    @patch("app.api.v1.endpoints.auth.otp_service.verify_otp")
    @patch("app.api.v1.endpoints.auth.format_to_e164")
    @patch(
        "app.services.stripe_service.customer_has_subscription_history",
    )
    @patch(
        "app.services.stripe_service.find_existing_customer_by_phone",
    )
    async def test_reattaches_and_stamps_history_flag(
        self,
        mock_find,
        mock_has_history,
        mock_format,
        mock_verify,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        phone = "+14155557777"
        mock_format.return_value = phone
        mock_verify.return_value = (True, "ok")
        # Helper returns dict-like; caller uses [] access so both real
        # Stripe SDK objects and test dicts work.
        mock_find.return_value = {"id": "cus_returning_001"}
        mock_has_history.return_value = True

        response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone_number": phone, "otp_code": "123456"},
        )

        assert response.status_code == 200
        # User exists in DB now with the re-attached customer + flag set.
        from app.crud import crud_user

        user = await crud_user.get_by_phone(db_session, phone_number=phone)
        assert user is not None
        assert user.stripe_customer_id == "cus_returning_001"
        assert user.had_prior_billing_history is True

    @patch("app.api.v1.endpoints.auth.otp_service.verify_otp")
    @patch("app.api.v1.endpoints.auth.format_to_e164")
    @patch(
        "app.services.stripe_service.find_existing_customer_by_phone",
    )
    @patch("app.services.stripe_service.get_or_create_stripe_customer")
    async def test_fresh_signup_creates_customer_when_no_match(
        self,
        mock_create,
        mock_find,
        mock_format,
        mock_verify,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        phone = "+14155557778"
        mock_format.return_value = phone
        mock_verify.return_value = (True, "ok")
        mock_find.return_value = None  # no existing customer
        mock_create.return_value = "cus_fresh_001"

        response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone_number": phone, "otp_code": "123456"},
        )

        assert response.status_code == 200
        mock_create.assert_awaited_once()


@pytest.mark.asyncio
class TestAccessFreeTrialDenial:
    async def test_trial_granted_for_honest_new_user(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155557900")
        access = await subscription_service.check_access(db_session, user)
        assert access.has_access is True
        assert access.reason == "free_trial"

    async def test_trial_denied_when_had_prior_history(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155557901")
        user.had_prior_billing_history = True
        await db_session.commit()

        access = await subscription_service.check_access(db_session, user)

        assert access.has_access is False
        assert access.reason == "none"
