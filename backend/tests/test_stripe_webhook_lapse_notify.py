"""Stripe webhook → sub-lapse notification dispatch.

Verifies the three webhook events that fire `notify_lapse`:
- `customer.subscription.updated` with cancel_at_period_end flipping true → T_ZERO
- `customer.subscription.deleted` → T_END
- `invoice.payment_failed` with next_payment_attempt=null → T_ZERO

Related: app/api/v1/endpoints/webhooks.py, app/services/sub_lapse_notifications.py
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import SubscriptionSource
from app.services.sub_lapse_notifications import Moment
from tests.helpers import create_test_subscription, create_test_user


def _mock_stripe_event(event_type: str, data_object: dict) -> MagicMock:
    event = MagicMock()
    event.type = event_type
    event.data.object = data_object
    return event


@pytest.mark.asyncio
class TestSubscriptionUpdatedCancelFlip:
    @patch("app.services.stripe_service.construct_webhook_event")
    @patch("app.api.v1.endpoints.webhooks.notify_lapse", new_callable=AsyncMock)
    async def test_t_zero_fires_when_renewing_to_cancel(
        self,
        mock_notify,
        mock_construct,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155558700", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_will_cancel"
        sub.auto_renew = True
        await db_session.commit()

        event = _mock_stripe_event("customer.subscription.updated", {
            "id": "sub_will_cancel",
            "current_period_end": int(
                (datetime.now(UTC) + timedelta(days=30)).timestamp()
            ),
            "cancel_at_period_end": True,
            "items": {"data": []},
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        mock_notify.assert_awaited_once()
        kwargs = mock_notify.await_args
        assert kwargs.args[2] == Moment.T_ZERO

    @patch("app.services.stripe_service.construct_webhook_event")
    @patch("app.api.v1.endpoints.webhooks.notify_lapse", new_callable=AsyncMock)
    async def test_no_notify_when_already_cancelling(
        self,
        mock_notify,
        mock_construct,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Stripe re-emits updates whenever anything changes (price,
        metadata). If auto_renew was already false, the user already
        got the T=0 notification — re-firing on every subsequent
        update would spam them."""
        owner = await create_test_user(
            db_session, phone_number="+14155558701", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_already_cancelled"
        sub.auto_renew = False  # already cancelling
        await db_session.commit()

        event = _mock_stripe_event("customer.subscription.updated", {
            "id": "sub_already_cancelled",
            "cancel_at_period_end": True,
            "items": {"data": []},
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        mock_notify.assert_not_awaited()

    @patch("app.services.stripe_service.construct_webhook_event")
    @patch("app.api.v1.endpoints.webhooks.notify_lapse", new_callable=AsyncMock)
    async def test_no_notify_on_normal_renewal(
        self,
        mock_notify,
        mock_construct,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155558702", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_renewing_normal"
        sub.auto_renew = True
        await db_session.commit()

        event = _mock_stripe_event("customer.subscription.updated", {
            "id": "sub_renewing_normal",
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

        mock_notify.assert_not_awaited()


@pytest.mark.asyncio
class TestSubscriptionDeleted:
    @patch("app.services.stripe_service.construct_webhook_event")
    @patch("app.api.v1.endpoints.webhooks.notify_lapse", new_callable=AsyncMock)
    async def test_t_end_fires_on_natural_lapse(
        self,
        mock_notify,
        mock_construct,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155558800", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_lapsed"
        await db_session.commit()

        event = _mock_stripe_event("customer.subscription.deleted", {
            "id": "sub_lapsed",
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        mock_notify.assert_awaited_once()
        assert mock_notify.await_args.args[2] == Moment.T_END


@pytest.mark.asyncio
class TestNotifyLapseFailureContained:
    @patch("app.services.stripe_service.construct_webhook_event")
    @patch("app.api.v1.endpoints.webhooks.notify_lapse", new_callable=AsyncMock)
    async def test_notify_exception_does_not_500_webhook(
        self,
        mock_notify,
        mock_construct,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """If notify_lapse raises, the webhook must still 200. Otherwise
        Stripe retries but the DB mutation already committed, so the
        retry's was_renewing check sees the new auto_renew=False and
        skips the notification — permanently losing it."""
        mock_notify.side_effect = RuntimeError("twilio down")
        owner = await create_test_user(
            db_session, phone_number="+14155558950", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_notify_fails"
        sub.auto_renew = True
        await db_session.commit()

        event = _mock_stripe_event("customer.subscription.updated", {
            "id": "sub_notify_fails",
            "cancel_at_period_end": True,
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
        assert sub.auto_renew is False


@pytest.mark.asyncio
class TestInvoicePaymentFailed:
    @patch("app.services.stripe_service.construct_webhook_event")
    @patch("app.api.v1.endpoints.webhooks.notify_lapse", new_callable=AsyncMock)
    async def test_t_zero_fires_when_retries_exhausted(
        self,
        mock_notify,
        mock_construct,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """next_payment_attempt=None signals Stripe gave up — fire T=0
        because the sub is about to be cancelled."""
        owner = await create_test_user(
            db_session, phone_number="+14155558900", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_payment_dead"
        await db_session.commit()

        event = _mock_stripe_event("invoice.payment_failed", {
            "subscription": "sub_payment_dead",
            "customer": "cus_x",
            "next_payment_attempt": None,
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        mock_notify.assert_awaited_once()
        assert mock_notify.await_args.args[2] == Moment.T_ZERO

    @patch("app.services.stripe_service.construct_webhook_event")
    @patch("app.api.v1.endpoints.webhooks.notify_lapse", new_callable=AsyncMock)
    async def test_no_notify_during_dunning_retry_window(
        self,
        mock_notify,
        mock_construct,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """During Stripe's retry window (next_payment_attempt is set),
        the payment may still succeed — don't spam dependents."""
        owner = await create_test_user(
            db_session, phone_number="+14155558901", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_payment_retrying"
        await db_session.commit()

        event = _mock_stripe_event("invoice.payment_failed", {
            "subscription": "sub_payment_retrying",
            "customer": "cus_x",
            "next_payment_attempt": int(
                (datetime.now(UTC) + timedelta(days=3)).timestamp()
            ),
        })
        mock_construct.return_value = event

        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response.status_code == 200

        mock_notify.assert_not_awaited()
