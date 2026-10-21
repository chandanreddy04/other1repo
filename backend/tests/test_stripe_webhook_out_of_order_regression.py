"""Regression for payments #4: out-of-order Stripe webhook delivery.

If customer.subscription.deleted is processed before a late
checkout.session.completed for the same subscription, we must not create an
ACTIVE local sub for an already-cancelled Stripe subscription. The checkout
handler now checks the live Stripe status first.

Related: app/api/v1/endpoints/webhooks.py, app/services/stripe_service.py.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import Subscription


def _event(event_id: str, data_object: dict) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    event.type = "checkout.session.completed"
    event.data.object = data_object
    return event


@pytest.mark.asyncio
@patch("app.services.stripe_service.get_subscription_status")
@patch("app.services.stripe_service.construct_webhook_event")
async def test_late_checkout_for_cancelled_sub_is_skipped(
    mock_construct, mock_status, client, test_user, db_session: AsyncSession
):
    mock_status.return_value = "canceled"  # Stripe already cancelled it
    mock_construct.return_value = _event(
        "evt_ooo_1",
        {
            "id": "cs_ooo_1",
            "subscription": "sub_ooo_cancelled",
            "metadata": {
                "type": "subscription",
                "user_id": str(test_user.id),
                "plan_type": "monthly",
            },
        },
    )

    resp = await client.post(
        "/webhooks/payments/stripe",
        content=b"payload",
        headers={"Stripe-Signature": "sig"},
    )
    assert resp.status_code == 200

    sub = (
        await db_session.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == "sub_ooo_cancelled"
            )
        )
    ).scalar_one_or_none()
    assert sub is None  # no ACTIVE local sub created for a cancelled Stripe sub
