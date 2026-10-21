"""
Tests for sponsorship request endpoint and related webhook fulfillment.

Covers:
  - POST /sponsorship-requests: auth, validation, DB record creation
  - Stripe webhook: gift subscription stacking, best-effort SR fulfillment
  - SponsorshipRequest CRUD: create, fulfill, get_pending_for_pair
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.phone_number import crud_phone_number
from app.crud.sponsor import crud_sponsorship_request
from app.models.sponsor import SponsorshipRequest, SponsorshipRequestStatus
from app.models.subscription import Subscription, SubscriptionSource, SubscriptionStatus
from app.services import subscription_service
from tests.helpers import create_test_user

BASE = "/api/v1/sponsorship-requests"
WEBHOOK_BASE = "/webhooks/payments/stripe"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _make_gift_event(
    recipient_phone: str,
    gifter_phone: str,
    plan_type: str = "monthly",
    session_id: str = "cs_test_123",
) -> dict:
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "metadata": {
                    "type": "gift_subscription",
                    "recipient_phone": recipient_phone,
                    "gifter_phone": gifter_phone,
                    "plan_type": plan_type,
                },
            }
        },
    }


# ---------------------------------------------------------------------------
# POST /sponsorship-requests
# ---------------------------------------------------------------------------


class TestCreateSponsorshipRequest:
    async def test_creates_record(self, client: AsyncClient, db_session: AsyncSession):
        user = await create_test_user(db_session, "+14155550001")
        resp = await client.post(
            BASE,
            json={"target_phone": "+14155550002"},
            headers=_auth(user),
        )
        assert resp.status_code == 201

        result = await db_session.execute(
            select(SponsorshipRequest).where(
                SponsorshipRequest.requester_phone_id == user.phone_number_id
            )
        )
        req = result.scalar_one()
        assert req.status == SponsorshipRequestStatus.PENDING.value
        assert req.fulfilled_at is None
        assert req.subscription_id is None

    async def test_target_phone_created_if_new(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155550003")
        await client.post(
            BASE,
            json={"target_phone": "+14155550099"},
            headers=_auth(user),
        )
        phone = await crud_phone_number.get_by_number(db_session, number="+14155550099")
        assert phone is not None

    async def test_invalid_phone_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155550004")
        resp = await client.post(
            BASE,
            json={"target_phone": "not-a-phone"},
            headers=_auth(user),
        )
        assert resp.status_code == 400

    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        resp = await client.post(BASE, json={"target_phone": "+14155550005"})
        assert resp.status_code == 401

    async def test_duplicate_request_is_idempotent(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155550006")
        for _ in range(2):
            resp = await client.post(
                BASE,
                json={"target_phone": "+14155550007"},
                headers=_auth(user),
            )
            assert resp.status_code == 201

        result = await db_session.execute(
            select(SponsorshipRequest).where(
                SponsorshipRequest.requester_phone_id == user.phone_number_id
            )
        )
        # A second ask for the same pair must NOT create a duplicate pending
        # row (it would break get_pending_for_pair / the partial-unique index).
        assert len(result.scalars().all()) == 1

    async def test_requested_at_is_set(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155550008")
        before = datetime.now(UTC)
        await client.post(
            BASE, json={"target_phone": "+14155550009"}, headers=_auth(user)
        )
        result = await db_session.execute(
            select(SponsorshipRequest).where(
                SponsorshipRequest.requester_phone_id == user.phone_number_id
            )
        )
        req = result.scalar_one()
        assert req.requested_at >= before

    async def test_missing_target_phone_returns_422(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155550010")
        resp = await client.post(BASE, json={}, headers=_auth(user))
        assert resp.status_code == 422

    async def test_user_without_profile_returns_428(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155550011", full_name=None)
        resp = await client.post(
            BASE,
            json={"target_phone": "+14155550012"},
            headers=_auth(user),
        )
        assert resp.status_code == 428

    async def test_requester_is_current_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155550013")
        await client.post(
            BASE, json={"target_phone": "+14155550014"}, headers=_auth(user)
        )
        result = await db_session.execute(
            select(SponsorshipRequest).where(
                SponsorshipRequest.requester_phone_id == user.phone_number_id
            )
        )
        req = result.scalar_one()
        assert req.requester_phone_id == user.phone_number_id

    async def test_target_phone_id_is_set(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155550015")
        target_number = "+14155550016"
        await client.post(
            BASE, json={"target_phone": target_number}, headers=_auth(user)
        )
        target_phone = await crud_phone_number.get_by_number(
            db_session, number=target_number
        )
        result = await db_session.execute(
            select(SponsorshipRequest).where(
                SponsorshipRequest.requester_phone_id == user.phone_number_id
            )
        )
        req = result.scalar_one()
        assert req.target_phone_id == target_phone.id


# ---------------------------------------------------------------------------
# CRUD: get_pending_for_pair / fulfill
# ---------------------------------------------------------------------------


class TestSponsorshipRequestCRUD:
    async def test_get_pending_for_pair_returns_none_when_missing(
        self, db_session: AsyncSession
    ):
        result = await crud_sponsorship_request.get_pending_for_pair(
            db_session,
            requester_phone_id=uuid.uuid4(),
            target_phone_id=uuid.uuid4(),
        )
        assert result is None

    async def test_get_pending_for_pair_finds_record(self, db_session: AsyncSession):
        p1, _ = await crud_phone_number.get_or_create(db_session, number="+14155551001")
        p2, _ = await crud_phone_number.get_or_create(db_session, number="+14155551002")
        req = SponsorshipRequest(
            requester_phone_id=p1.id,
            target_phone_id=p2.id,
        )
        db_session.add(req)
        await db_session.commit()
        await db_session.refresh(req)

        found = await crud_sponsorship_request.get_pending_for_pair(
            db_session,
            requester_phone_id=p1.id,
            target_phone_id=p2.id,
        )
        assert found is not None
        assert found.id == req.id

    async def test_fulfill_sets_status_and_timestamps(self, db_session: AsyncSession):
        p1, _ = await crud_phone_number.get_or_create(db_session, number="+14155551003")
        p2, _ = await crud_phone_number.get_or_create(db_session, number="+14155551004")

        user = await create_test_user(db_session, phone_number="+14155551099")
        sub = Subscription(
            user_id=user.id,
            phone_number_id=user.phone_number_id,
            plan_type="monthly",
            status=SubscriptionStatus.ACTIVE.value,
            source=SubscriptionSource.STRIPE_GIFT.value,
            current_period_start=datetime.now(UTC),
            current_period_end=datetime.now(UTC) + timedelta(days=30),
        )
        db_session.add(sub)
        await db_session.commit()
        await db_session.refresh(sub)

        req = SponsorshipRequest(requester_phone_id=p1.id, target_phone_id=p2.id)
        db_session.add(req)
        await db_session.commit()
        await db_session.refresh(req)

        fulfilled = await crud_sponsorship_request.fulfill(
            db_session, request=req, subscription_id=sub.id
        )
        assert fulfilled.status == SponsorshipRequestStatus.FULFILLED.value
        assert fulfilled.fulfilled_at is not None
        assert fulfilled.subscription_id == sub.id

    async def test_get_pending_ignores_fulfilled(self, db_session: AsyncSession):
        p1, _ = await crud_phone_number.get_or_create(db_session, number="+14155551005")
        p2, _ = await crud_phone_number.get_or_create(db_session, number="+14155551006")
        req = SponsorshipRequest(
            requester_phone_id=p1.id,
            target_phone_id=p2.id,
            status=SponsorshipRequestStatus.FULFILLED.value,
        )
        db_session.add(req)
        await db_session.commit()

        found = await crud_sponsorship_request.get_pending_for_pair(
            db_session, requester_phone_id=p1.id, target_phone_id=p2.id
        )
        assert found is None


# ---------------------------------------------------------------------------
# Subscription stacking
# ---------------------------------------------------------------------------


class TestSubscriptionStacking:
    async def test_get_stack_start_returns_now_when_no_subs(
        self, db_session: AsyncSession
    ):
        phone, _ = await crud_phone_number.get_or_create(
            db_session, number="+14155552001"
        )
        before = datetime.now(UTC)
        start = await subscription_service.get_stack_start(db_session, phone.id)
        assert start >= before

    async def test_get_stack_start_returns_furthest_end(self, db_session: AsyncSession):
        user = await create_test_user(db_session, "+14155552002")
        now = datetime.now(UTC)
        far_end = now + timedelta(days=60)

        sub = Subscription(
            user_id=user.id,
            phone_number_id=user.phone_number_id,
            plan_type="monthly",
            status=SubscriptionStatus.ACTIVE.value,
            source=SubscriptionSource.STRIPE_WEB.value,
            current_period_start=now,
            current_period_end=far_end,
        )
        db_session.add(sub)
        await db_session.commit()

        start = await subscription_service.get_stack_start(
            db_session, user.phone_number_id
        )
        assert abs((start - far_end).total_seconds()) < 1

    async def test_get_stack_start_uses_furthest_of_multiple_subs(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, "+14155552004")
        now = datetime.now(UTC)
        ends = [now + timedelta(days=d) for d in (15, 45, 30)]

        for end in ends:
            sub = Subscription(
                user_id=user.id,
                phone_number_id=user.phone_number_id,
                plan_type="monthly",
                status=SubscriptionStatus.ACTIVE.value,
                source=SubscriptionSource.STRIPE_WEB.value,
                current_period_start=now,
                current_period_end=end,
            )
            db_session.add(sub)
        await db_session.commit()

        start = await subscription_service.get_stack_start(
            db_session, user.phone_number_id
        )
        assert abs((start - max(ends)).total_seconds()) < 1

    async def test_get_stack_start_ignores_expired_subs(self, db_session: AsyncSession):
        user = await create_test_user(db_session, "+14155552003")
        now = datetime.now(UTC)

        sub = Subscription(
            user_id=user.id,
            phone_number_id=user.phone_number_id,
            plan_type="monthly",
            status=SubscriptionStatus.EXPIRED.value,
            source=SubscriptionSource.STRIPE_WEB.value,
            current_period_start=now - timedelta(days=30),
            current_period_end=now - timedelta(days=1),
        )
        db_session.add(sub)
        await db_session.commit()

        start = await subscription_service.get_stack_start(
            db_session, user.phone_number_id
        )
        assert start >= now - timedelta(seconds=5)


# ---------------------------------------------------------------------------
# Stripe webhook: gift + SR fulfillment
# ---------------------------------------------------------------------------


class TestStripeWebhookGift:
    def _mock_event(self, payload: dict):
        mock_event = MagicMock()
        mock_event.type = payload["type"]
        mock_event.data.object = payload["data"]["object"]
        return mock_event

    async def test_gift_creates_subscription(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        recipient = await create_test_user(db_session, "+14155553001")
        event = await _make_gift_event("+14155553001", "+14155553002")

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=self._mock_event(event),
        ):
            resp = await client.post(
                WEBHOOK_BASE,
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )

        assert resp.status_code == 200
        result = await db_session.execute(
            select(Subscription).where(
                Subscription.user_id == recipient.id,
                Subscription.source == SubscriptionSource.STRIPE_GIFT.value,
            )
        )
        assert result.scalar_one_or_none() is not None

    async def test_gift_fulfills_pending_request(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        recipient = await create_test_user(db_session, "+14155553003")
        gifter_phone, _ = await crud_phone_number.get_or_create(
            db_session, number="+14155553004"
        )

        req = SponsorshipRequest(
            requester_phone_id=recipient.phone_number_id,
            target_phone_id=gifter_phone.id,
        )
        db_session.add(req)
        await db_session.commit()
        await db_session.refresh(req)

        event = await _make_gift_event("+14155553003", "+14155553004")
        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=self._mock_event(event),
        ):
            await client.post(
                WEBHOOK_BASE,
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )

        await db_session.refresh(req)
        assert req.status == SponsorshipRequestStatus.FULFILLED.value
        assert req.fulfilled_at is not None

    async def test_gift_no_pending_request_still_succeeds(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(db_session, "+14155553005")
        event = await _make_gift_event("+14155553005", "+14155553006")

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=self._mock_event(event),
        ):
            resp = await client.post(
                WEBHOOK_BASE,
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )
        assert resp.status_code == 200

    async def test_gift_sets_gifted_by_phone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        recipient = await create_test_user(db_session, "+14155553009")
        event = await _make_gift_event("+14155553009", "+14155553010")

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=self._mock_event(event),
        ):
            await client.post(
                WEBHOOK_BASE,
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )

        result = await db_session.execute(
            select(Subscription).where(
                Subscription.user_id == recipient.id,
                Subscription.source == SubscriptionSource.STRIPE_GIFT.value,
            )
        )
        sub = result.scalar_one()
        assert sub.gifted_by_phone is not None

    async def test_gift_non_gift_event_ignored(self, client: AsyncClient):
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"
        mock_event.data.object = {"id": "cs_test", "metadata": {"type": "other"}}

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=mock_event,
        ):
            resp = await client.post(
                WEBHOOK_BASE,
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    async def test_gift_invalid_recipient_phone_returns_invalid_phone(
        self, client: AsyncClient
    ):
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"
        data = {
            "id": "cs_test",
            "metadata": {
                "type": "gift_subscription",
                "recipient_phone": "invalid",
                "gifter_phone": "+14155553099",
                "plan_type": "monthly",
            },
        }
        mock_event.data.object = data

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=mock_event,
        ):
            resp = await client.post(
                WEBHOOK_BASE,
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )
        assert resp.json()["status"] == "invalid_phone"

    async def test_gift_annual_plan_creates_365_day_sub(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        recipient = await create_test_user(db_session, "+14155554001")
        event = await _make_gift_event(
            "+14155554001", "+14155554002", plan_type="annual"
        )

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=self._mock_event(event),
        ):
            await client.post(
                WEBHOOK_BASE,
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )

        result = await db_session.execute(
            select(Subscription).where(
                Subscription.user_id == recipient.id,
                Subscription.source == SubscriptionSource.STRIPE_GIFT.value,
            )
        )
        sub = result.scalar_one()
        duration = sub.current_period_end - sub.current_period_start
        assert duration.days >= 364

    async def test_crud_fulfill_updates_subscription_id(
        self, db_session: AsyncSession
    ):
        p1, _ = await crud_phone_number.get_or_create(db_session, number="+14155551007")
        p2, _ = await crud_phone_number.get_or_create(db_session, number="+14155551008")

        user = await create_test_user(db_session, phone_number="+14155551098")
        sub = Subscription(
            user_id=user.id,
            phone_number_id=user.phone_number_id,
            plan_type="monthly",
            status=SubscriptionStatus.ACTIVE.value,
            source=SubscriptionSource.STRIPE_GIFT.value,
            current_period_start=datetime.now(UTC),
            current_period_end=datetime.now(UTC) + timedelta(days=30),
        )
        db_session.add(sub)
        await db_session.commit()
        await db_session.refresh(sub)

        req = SponsorshipRequest(requester_phone_id=p1.id, target_phone_id=p2.id)
        db_session.add(req)
        await db_session.commit()
        await db_session.refresh(req)

        fulfilled = await crud_sponsorship_request.fulfill(
            db_session, request=req, subscription_id=sub.id
        )
        assert fulfilled.subscription_id == sub.id

    async def test_gift_stacks_on_existing_subscription(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        recipient = await create_test_user(db_session, "+14155553007")
        now = datetime.now(UTC)
        existing_end = now + timedelta(days=30)

        existing_sub = Subscription(
            user_id=recipient.id,
            phone_number_id=recipient.phone_number_id,
            plan_type="monthly",
            status=SubscriptionStatus.ACTIVE.value,
            source=SubscriptionSource.STRIPE_WEB.value,
            current_period_start=now,
            current_period_end=existing_end,
        )
        db_session.add(existing_sub)
        await db_session.commit()

        event = await _make_gift_event("+14155553007", "+14155553008")
        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=self._mock_event(event),
        ):
            await client.post(
                WEBHOOK_BASE,
                content=b"payload",
                headers={"Stripe-Signature": "sig"},
            )

        result = await db_session.execute(
            select(Subscription).where(
                Subscription.user_id == recipient.id,
                Subscription.source == SubscriptionSource.STRIPE_GIFT.value,
            )
        )
        gift_sub = result.scalar_one()
        # Should start at or after the existing subscription ends
        assert gift_sub.current_period_start >= existing_end - timedelta(seconds=1)
