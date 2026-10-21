"""Regression for payments #1: reconcile a paid sub whose webhook was lost.

If checkout.session.completed never arrives, a user is charged but has no local
Subscription and check_access denies them. When otherwise fully denied (and the
Stripe customer is real), check_access now asks Stripe for active subscriptions
and backfills any we're missing.

Related: app/services/subscription_service.py (reconcile_subscription_from_stripe).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.subscription import Subscription
from app.services import subscription_service
from tests.helpers import create_test_user


@pytest.mark.asyncio
@patch("app.services.stripe_service.list_active_subscriptions")
async def test_check_access_reconciles_lost_subscription(
    mock_list, db_session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(settings, "STRIPE_PRICE_ID_MONTHLY", "price_test_monthly")

    user = await create_test_user(db_session, phone_number="+14155566001")
    # Real Stripe customer, and skip the free-trial branch so we reach the
    # reconcile step (would otherwise be denied).
    user.stripe_customer_id = "cus_real_1"
    user.had_prior_billing_history = True
    await db_session.commit()

    future_ts = int((datetime.now(UTC) + timedelta(days=30)).timestamp())
    mock_list.return_value = [
        {
            "id": "sub_reconcile_1",
            "current_period_end": future_ts,
            "items": {"data": [{"price": {"id": "price_test_monthly"}}]},
        }
    ]

    resp = await subscription_service.check_access(db_session, user)

    assert resp.has_access is True
    assert resp.reason == "subscription"
    sub = (
        await db_session.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == "sub_reconcile_1"
            )
        )
    ).scalar_one_or_none()
    assert sub is not None
    assert sub.user_id == user.id

    # A pending (placeholder) customer must NOT trigger a Stripe call.
    mock_list.reset_mock()
    user2 = await create_test_user(db_session, phone_number="+14155566002")
    user2.had_prior_billing_history = True
    await db_session.commit()
    await subscription_service.check_access(db_session, user2)
    mock_list.assert_not_called()
