"""Regression for payments H2: Stripe webhook idempotency.

The ProcessedStripeEvent marker is now inserted+flushed BEFORE the handler and
committed in the same transaction as the effect (was committed separately
after), so a redelivered event can't double-apply and a crash can't leave an
effect without its marker. Ignored events must NOT burn a marker.

Related: app/api/v1/endpoints/webhooks.py.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.processed_stripe_event import ProcessedStripeEvent
from app.models.subscription import Subscription


def _event(event_id: str, event_type: str, data_object: dict) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    event.type = event_type
    event.data.object = data_object
    return event


@pytest.mark.asyncio
class TestWebhookIdempotency:
    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_redelivered_event_applies_effect_once(
        self, mock_construct, client, test_user, db_session: AsyncSession
    ):
        event = _event(
            "evt_idem_1",
            "checkout.session.completed",
            {
                "id": "cs_idem_1",
                "subscription": "sub_idem_1",
                "metadata": {
                    "type": "subscription",
                    "user_id": str(test_user.id),
                    "plan_type": "monthly",
                },
            },
        )
        mock_construct.return_value = event

        for _ in range(2):  # Stripe delivers at-least-once
            resp = await client.post(
                "/webhooks/payments/stripe",
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )
            assert resp.status_code == 200

        subs = await db_session.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.stripe_subscription_id == "sub_idem_1")
        )
        assert subs == 1  # effect applied exactly once
        markers = await db_session.scalar(
            select(func.count())
            .select_from(ProcessedStripeEvent)
            .where(ProcessedStripeEvent.event_id == "evt_idem_1")
        )
        assert markers == 1

    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_ignored_event_does_not_record_marker(
        self, mock_construct, client, db_session: AsyncSession
    ):
        event = _event(
            "evt_ignored_1",
            "checkout.session.completed",
            {"id": "cs_ign_1", "metadata": {"type": "something_unknown"}},
        )
        mock_construct.return_value = event

        resp = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

        marker = await db_session.scalar(
            select(ProcessedStripeEvent).where(
                ProcessedStripeEvent.event_id == "evt_ignored_1"
            )
        )
        assert marker is None  # ignored events don't burn a marker
