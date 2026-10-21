"""Tests for the native cancel/reactivate flow — PATCH /api/v1/subscriptions.

Covers the in-app "manage subscription" action (owner-decision design): a
self-paid recurring Stripe subscription can be cancelled at period end and
reactivated natively, while gift / comp / day-pass access is not manageable
here (change-plan + payment-method stay on the hosted portal). Also pins the
new `source` / `cancel_at_period_end` fields on the status response.

Related: app/api/v1/endpoints/subscriptions.py (update_subscription),
app/services/subscription_service.py (get_cancelable_subscription, check_access).
"""

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import create_test_subscription


async def _make_sub(
    db: AsyncSession,
    user,
    *,
    plan_type: str = "monthly",
    source: str = "stripe_web",
    stripe_subscription_id: str | None = "sub_test123",
    auto_renew: bool = True,
):
    """Active subscription with the recurring-Stripe fields the cancel guard
    inspects (the shared helper leaves them at defaults)."""
    sub = await create_test_subscription(
        db, user, plan_type=plan_type, source=source
    )
    sub.stripe_subscription_id = stripe_subscription_id
    sub.auto_renew = auto_renew
    await db.commit()
    await db.refresh(sub)
    return sub


@pytest.mark.asyncio
class TestCancelReactivate:
    @patch("app.api.v1.endpoints.subscriptions.cancel_subscription_at_period_end")
    async def test_cancel_success(
        self, mock_cancel, client, test_user, auth_headers, db_session: AsyncSession
    ):
        await _make_sub(db_session, test_user)

        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
            headers=auth_headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["cancel_at_period_end"] is True
        assert body["source"] == "stripe_web"
        assert body["has_access"] is True
        mock_cancel.assert_called_once_with("sub_test123")

    @patch("app.api.v1.endpoints.subscriptions.reactivate_subscription")
    async def test_reactivate_success(
        self, mock_reactivate, client, test_user, auth_headers, db_session: AsyncSession
    ):
        await _make_sub(db_session, test_user, auto_renew=False)

        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["cancel_at_period_end"] is False
        mock_reactivate.assert_called_once_with("sub_test123")

    async def test_cancel_no_subscription_404(
        self, client, test_user, auth_headers
    ):
        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_cancel_gift_rejected_404(
        self, client, test_user, auth_headers, db_session: AsyncSession
    ):
        # Even with a subscription id present, a gift isn't the recipient's to cancel.
        await _make_sub(db_session, test_user, source="stripe_gift")

        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_cancel_comp_rejected_404(
        self, client, test_user, auth_headers, db_session: AsyncSession
    ):
        await _make_sub(db_session, test_user, source="comp")

        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_cancel_day_pass_rejected_404(
        self, client, test_user, auth_headers, db_session: AsyncSession
    ):
        # day_pass is a one-time purchase — nothing recurring to toggle.
        await _make_sub(db_session, test_user, plan_type="day_pass")

        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_cancel_without_stripe_sub_id_404(
        self, client, test_user, auth_headers, db_session: AsyncSession
    ):
        await _make_sub(db_session, test_user, stripe_subscription_id=None)

        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
            headers=auth_headers,
        )
        assert response.status_code == 404

    @patch("app.api.v1.endpoints.subscriptions.cancel_subscription_at_period_end")
    async def test_cancel_502_on_stripe_error(
        self, mock_cancel, client, test_user, auth_headers, db_session: AsyncSession
    ):
        import stripe

        await _make_sub(db_session, test_user)
        mock_cancel.side_effect = stripe.StripeError("API error")

        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
            headers=auth_headers,
        )
        assert response.status_code == 502

    @patch("app.api.v1.endpoints.subscriptions.cancel_subscription_at_period_end")
    async def test_cancel_group_owner_success(
        self, mock_cancel, client, test_user, auth_headers, db_session: AsyncSession
    ):
        # A group owner's own recurring group sub is cancelable (period-end
        # cancel flows into the existing member-grace path).
        await _make_sub(db_session, test_user, plan_type="group_annual")

        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
            headers=auth_headers,
        )
        assert response.status_code == 200
        mock_cancel.assert_called_once()

    async def test_patch_unauthenticated_401(self, client):
        response = await client.patch(
            "/api/v1/subscriptions",
            json={"cancel_at_period_end": True},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
class TestStatusExposesManageFields:
    async def test_active_sub_exposes_source_and_renewing(
        self, client, test_user, auth_headers, db_session: AsyncSession
    ):
        await _make_sub(db_session, test_user, auto_renew=True)

        response = await client.get(
            "/api/v1/subscriptions", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "stripe_web"
        assert body["cancel_at_period_end"] is False

    async def test_no_access_omits_manage_fields(
        self, client, test_user, auth_headers, db_session: AsyncSession
    ):
        # test_user has no subscription; free trial may grant access but the
        # manage fields stay null (no backing Subscription row).
        response = await client.get(
            "/api/v1/subscriptions", headers=auth_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["source"] is None
        assert body["cancel_at_period_end"] is None
