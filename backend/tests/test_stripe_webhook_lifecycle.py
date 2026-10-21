"""Tests for Stripe webhook subscription lifecycle events."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import (
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from tests.helpers import create_test_subscription


def _mock_stripe_event(event_type: str, data_object: dict) -> MagicMock:
    event = MagicMock()
    event.type = event_type
    event.data.object = data_object
    return event


@pytest.mark.asyncio
class TestStripeWebhookSubscriptionCheckout:
    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_subscription_checkout_creates_sub(
        self, mock_construct, client, test_user, db_session: AsyncSession
    ):
        event = _mock_stripe_event("checkout.session.completed", {
            "id": "cs_test_123",
            "subscription": "sub_stripe_abc",
            "metadata": {
                "type": "subscription",
                "user_id": str(test_user.id),
                "plan_type": "monthly",
            },
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        result = await db_session.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == "sub_stripe_abc"
            )
        )
        sub = result.scalar_one_or_none()
        assert sub is not None
        assert sub.source == SubscriptionSource.STRIPE_WEB.value
        assert sub.plan_type == "monthly"

    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_group_checkout_creates_group_plan(
        self, mock_construct, client, test_user, db_session: AsyncSession
    ):
        event = _mock_stripe_event("checkout.session.completed", {
            "id": "cs_test_fam",
            "subscription": "sub_stripe_fam",
            "metadata": {
                "type": "subscription",
                "user_id": str(test_user.id),
                "plan_type": "group_monthly",
            },
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        from app.models.group_plan import GroupPlan

        result = await db_session.execute(select(GroupPlan))
        plans = result.scalars().all()
        assert any(p.owner_user_id == test_user.id for p in plans)


@pytest.mark.asyncio
class TestStripeWebhookSubscriptionUpdated:
    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_updates_period_end(
        self, mock_construct, client, test_user, db_session: AsyncSession
    ):
        sub = await create_test_subscription(
            db_session, test_user, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_update_test"
        await db_session.commit()

        new_end = int((datetime.now(UTC) + timedelta(days=60)).timestamp())
        event = _mock_stripe_event("customer.subscription.updated", {
            "id": "sub_update_test",
            "current_period_end": new_end,
            "cancel_at_period_end": False,
            "items": {"data": []},
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        await db_session.refresh(sub)
        assert sub.current_period_end.timestamp() == pytest.approx(new_end, abs=1)


@pytest.mark.asyncio
class TestStripeWebhookSubscriptionDeleted:
    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_cancels_subscription(
        self, mock_construct, client, test_user, db_session: AsyncSession
    ):
        sub = await create_test_subscription(
            db_session, test_user, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_delete_test"
        await db_session.commit()

        event = _mock_stripe_event("customer.subscription.deleted", {
            "id": "sub_delete_test",
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        await db_session.refresh(sub)
        assert sub.status == SubscriptionStatus.CANCELLED.value
        assert sub.auto_renew is False


@pytest.mark.asyncio
class TestStripeWebhookInvoicePaid:
    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_extends_period_on_renewal(
        self, mock_construct, client, test_user, db_session: AsyncSession
    ):
        sub = await create_test_subscription(
            db_session, test_user, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_invoice_test"
        await db_session.commit()

        new_end = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
        event = _mock_stripe_event("invoice.payment_succeeded", {
            "subscription": "sub_invoice_test",
            "billing_reason": "subscription_cycle",
            "lines": {"data": [{"period": {"end": new_end}}]},
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        await db_session.refresh(sub)
        assert sub.current_period_end.timestamp() == pytest.approx(new_end, abs=1)

    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_skips_initial_invoice(
        self, mock_construct, client, test_user, db_session: AsyncSession
    ):
        sub = await create_test_subscription(
            db_session, test_user, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_initial_test"
        original_end = sub.current_period_end
        await db_session.commit()

        event = _mock_stripe_event("invoice.payment_succeeded", {
            "subscription": "sub_initial_test",
            "billing_reason": "subscription_create",
            "lines": {"data": [{"period": {"end": 9999999999}}]},
        })
        mock_construct.return_value = event

        await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )

        await db_session.refresh(sub)
        assert sub.current_period_end == original_end


@pytest.mark.asyncio
class TestStripeWebhookInvoiceFailed:
    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_logs_and_returns_ok(
        self, mock_construct, client
    ):
        event = _mock_stripe_event("invoice.payment_failed", {
            "customer": "cus_test",
            "subscription": "sub_test",
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
