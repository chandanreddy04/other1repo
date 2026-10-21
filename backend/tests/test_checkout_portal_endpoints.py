"""Tests for subscription checkout and portal endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import create_test_subscription


@pytest.mark.asyncio
class TestCheckoutEndpoint:
    @patch("app.api.v1.endpoints.subscriptions.create_subscription_checkout_session")
    @patch("app.api.v1.endpoints.subscriptions.get_or_create_stripe_customer")
    async def test_checkout_success_monthly(self, mock_customer, mock_session, client, test_user, auth_headers):
        mock_customer.return_value = "cus_test123"
        mock_session.return_value = MagicMock(url="https://checkout.stripe.com/c/pay_123")

        response = await client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_type": "monthly"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "checkout.stripe.com" in response.json()["checkout_url"]

    @patch("app.api.v1.endpoints.subscriptions.create_subscription_checkout_session")
    @patch("app.api.v1.endpoints.subscriptions.get_or_create_stripe_customer")
    async def test_checkout_success_group_annual(self, mock_customer, mock_session, client, test_user, auth_headers):
        mock_customer.return_value = "cus_test123"
        mock_session.return_value = MagicMock(url="https://checkout.stripe.com/c/pay_456")

        response = await client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_type": "group_annual"},
            headers=auth_headers,
        )
        assert response.status_code == 200

    async def test_checkout_unauthenticated(self, client):
        response = await client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_type": "monthly"},
        )
        assert response.status_code == 401

    async def test_checkout_invalid_plan_type(self, client, auth_headers):
        response = await client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_type": "platinum"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    @patch("app.api.v1.endpoints.subscriptions.get_or_create_stripe_customer")
    async def test_checkout_already_subscribed(
        self, mock_customer, client, test_user, auth_headers, db_session: AsyncSession
    ):
        mock_customer.return_value = "cus_test123"
        await create_test_subscription(db_session, test_user, source="stripe_web")

        response = await client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_type": "monthly"},
            headers=auth_headers,
        )
        assert response.status_code == 409

    @patch("app.api.v1.endpoints.subscriptions.get_or_create_stripe_customer")
    async def test_checkout_503_when_pending_customer(self, mock_customer, client, auth_headers):
        mock_customer.return_value = "pending:some-uuid"

        response = await client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_type": "monthly"},
            headers=auth_headers,
        )
        assert response.status_code == 503

    @patch("app.api.v1.endpoints.subscriptions.create_subscription_checkout_session")
    @patch("app.api.v1.endpoints.subscriptions.get_or_create_stripe_customer")
    async def test_checkout_502_on_stripe_error(self, mock_customer, mock_session, client, auth_headers):
        import stripe

        mock_customer.return_value = "cus_test123"
        mock_session.side_effect = stripe.StripeError("API error")

        response = await client.post(
            "/api/v1/subscriptions/checkout",
            json={"plan_type": "monthly"},
            headers=auth_headers,
        )
        assert response.status_code == 502


@pytest.mark.asyncio
class TestPortalEndpoint:
    @patch("app.api.v1.endpoints.subscriptions.create_portal_session")
    async def test_portal_success(self, mock_portal, client, auth_headers, test_user, db_session: AsyncSession):
        test_user.stripe_customer_id = "cus_portal123"
        await db_session.commit()
        mock_portal.return_value = MagicMock(url="https://billing.stripe.com/p/session_abc")

        response = await client.post(
            "/api/v1/subscriptions/portal",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "billing.stripe.com" in response.json()["portal_url"]

    async def test_portal_unauthenticated(self, client):
        response = await client.post("/api/v1/subscriptions/portal")
        assert response.status_code == 401

    async def test_portal_503_when_pending_customer(self, client, auth_headers):
        response = await client.post(
            "/api/v1/subscriptions/portal",
            headers=auth_headers,
        )
        assert response.status_code == 503

    @patch("app.api.v1.endpoints.subscriptions.create_portal_session")
    async def test_portal_502_on_stripe_error(self, mock_portal, client, auth_headers, test_user, db_session: AsyncSession):
        import stripe

        test_user.stripe_customer_id = "cus_portal456"
        await db_session.commit()
        mock_portal.side_effect = stripe.StripeError("Portal error")

        response = await client.post(
            "/api/v1/subscriptions/portal",
            headers=auth_headers,
        )
        assert response.status_code == 502
