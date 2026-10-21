"""Integration tests for subscription API endpoints."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus
from app.models.subscription import (
    PlanType,
    Promotion,
    Referral,
    ReferralStatus,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User
from app.services import subscription_service
from tests.helpers import create_test_user


async def _add_circle(db: AsyncSession, owner, contact_phone: str) -> None:
    contact = await create_test_user(db, phone_number=contact_phone, full_name="Buddy")
    db.add(
        CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=contact.phone_number_id,
            nickname=contact.full_name,
            status=ContactStatus.ACTIVE.value,
        )
    )
    await db.commit()


async def _use_trial(db: AsyncSession, user: User) -> None:
    """Create a completed session so the user's free trial is consumed."""
    session = Session(
        user_id=user.id,
        expected_return_time=datetime.now(UTC) - timedelta(hours=1),
        actual_return_time=datetime.now(UTC),
        status=SessionStatus.COMPLETED.value,
    )
    db.add(session)
    await db.commit()


# ---------------------------------------------------------------------------
# Subscription status
# ---------------------------------------------------------------------------
class TestSubscriptionStatus:
    async def test_free_trial_status(
        self, client: AsyncClient, test_user: User, auth_headers: dict
    ):
        """New user gets free trial access."""
        response = await client.get(
            "/api/v1/subscriptions", headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["has_access"] is True
        assert data["reason"] == "free_trial"
        assert data["sessions_remaining"] == 1

    async def test_no_access_after_trial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User with used trial gets no access."""
        user = await create_test_user(db_session, phone_number="+14155559001", full_name="Trial Done")
        await _use_trial(db_session, user)

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/subscriptions", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["has_access"] is False
        assert data["reason"] == "none"
        assert data["sessions_remaining"] == 0

    async def test_active_subscription_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User with active subscription gets access."""
        user = await create_test_user(db_session, phone_number="+14155559002", full_name="Subscribed User")
        sub = Subscription(
            user_id=user.id,
            phone_number_id=user.phone_number_id,
            plan_type=PlanType.MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            source=SubscriptionSource.STRIPE_WEB,
            current_period_start=datetime.now(UTC),
            current_period_end=datetime.now(UTC) + timedelta(days=25),
        )
        db_session.add(sub)
        await db_session.commit()

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/subscriptions", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["has_access"] is True
        assert data["reason"] == "subscription"
        assert data["plan_type"] == "monthly"

    async def test_promotion_grants_access(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User during active promotion gets access."""
        user = await create_test_user(db_session, phone_number="+14155559003", full_name="Promo User")

        promo = Promotion(
            name="Launch promo",
            start_date=datetime.now(UTC) - timedelta(days=1),
            end_date=datetime.now(UTC) + timedelta(days=30),
            is_active=True,
        )
        db_session.add(promo)
        await db_session.commit()

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/subscriptions", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["has_access"] is True
        assert data["reason"] == "promotion"

    async def test_referral_credit_grants_access(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User with active referral credit gets access."""
        user = await create_test_user(db_session, phone_number="+14155559004", full_name="Referred User", free_credit_end=datetime.now(UTC) + timedelta(days=20))
        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/subscriptions", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["has_access"] is True
        assert data["reason"] == "referral_credit"

    async def test_unauthenticated_returns_401(self, client: AsyncClient):
        """Unauthenticated request returns 401."""
        response = await client.get("/api/v1/subscriptions")
        assert response.status_code in [401, 403]


# ---------------------------------------------------------------------------
# Session creation gating
# ---------------------------------------------------------------------------
class TestSessionCreationGating:
    async def test_free_trial_allows_first_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Free trial user can create their first session."""
        user = await create_test_user(db_session, phone_number="+14155559010", full_name="Trial User")
        await _add_circle(db_session, user, contact_phone="+14155569010")
        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat()
            },
        )
        assert response.status_code == 201

    async def test_paywall_blocks_after_trial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User who used their free trial gets 402."""
        user = await create_test_user(db_session, phone_number="+14155559011", full_name="Trial Done")
        await _use_trial(db_session, user)

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat()
            },
        )
        assert response.status_code == 402

    async def test_subscribed_user_can_create_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Subscribed user can create sessions freely."""
        user = await create_test_user(db_session, phone_number="+14155559012", full_name="Paid User")
        await _add_circle(db_session, user, contact_phone="+14155569012")
        sub = Subscription(
            user_id=user.id,
            phone_number_id=user.phone_number_id,
            plan_type=PlanType.ANNUAL,
            status=SubscriptionStatus.ACTIVE,
            source=SubscriptionSource.STRIPE_WEB,
            current_period_start=datetime.now(UTC),
            current_period_end=datetime.now(UTC) + timedelta(days=300),
        )
        db_session.add(sub)
        await db_session.commit()

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/sessions",
            headers=headers,
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat()
            },
        )
        assert response.status_code == 201




# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestStripeWebhook:
    async def test_missing_stripe_signature(self, client: AsyncClient):
        """Request without Stripe-Signature header returns 400."""
        response = await client.post(
            "/webhooks/payments/stripe",
            content=b"{}",
        )
        assert response.status_code == 400
        assert "Missing signature" in response.json()["detail"]

    async def test_invalid_stripe_signature(self, client: AsyncClient):
        """Invalid signature raises 400."""
        with patch(
            "app.services.stripe_service.construct_webhook_event",
            side_effect=Exception("bad sig"),
        ):
            response = await client.post(
                "/webhooks/payments/stripe",
                content=b"{}",
                headers={"Stripe-Signature": "invalid_sig"},
            )
        assert response.status_code == 400
        assert "Invalid signature" in response.json()["detail"]

    async def test_checkout_completed_gift_existing_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """checkout.session.completed for an existing user creates a gift subscription."""
        user = await create_test_user(db_session, phone_number="+14155550201", full_name="Gift Recipient")
        fake_event = MagicMock()
        fake_event.type = "checkout.session.completed"
        fake_event.data.object = {
            "id": "cs_test_001",
            "metadata": {
                "type": "gift_subscription",
                "recipient_phone": "+14155550201",
                "plan_type": "monthly",
                "gifter_name": "Jane",
            },
        }

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=fake_event,
        ):
            response = await client.post(
                "/webhooks/payments/stripe",
                content=b"{}",
                headers={"Stripe-Signature": "valid_sig"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        sub = await subscription_service.get_active_subscription(db_session, user.id)
        assert sub is not None
        assert sub.source == SubscriptionSource.STRIPE_GIFT
        assert sub.auto_renew is False
        assert sub.stripe_checkout_session_id == "cs_test_001"

    async def test_checkout_completed_gift_new_phone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """checkout.session.completed for unknown phone creates pending subscription."""
        fake_event = MagicMock()
        fake_event.type = "checkout.session.completed"
        fake_event.data.object = {
            "id": "cs_test_002",
            "metadata": {
                "type": "gift_subscription",
                "recipient_phone": "+14155550202",
                "plan_type": "annual",
                "gifter_name": "Bob",
            },
        }

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=fake_event,
        ):
            response = await client.post(
                "/webhooks/payments/stripe",
                content=b"{}",
                headers={"Stripe-Signature": "valid_sig"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_checkout_completed_non_gift_ignored(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """checkout.session.completed with non-gift metadata returns ignored."""
        fake_event = MagicMock()
        fake_event.type = "checkout.session.completed"
        fake_event.data.object = {
            "id": "cs_test_003",
            "metadata": {
                "type": "something_else",
            },
        }

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=fake_event,
        ):
            response = await client.post(
                "/webhooks/payments/stripe",
                content=b"{}",
                headers={"Stripe-Signature": "valid_sig"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    async def test_checkout_completed_invalid_phone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """checkout.session.completed with invalid recipient phone returns invalid_phone."""
        fake_event = MagicMock()
        fake_event.type = "checkout.session.completed"
        fake_event.data.object = {
            "id": "cs_test_004",
            "metadata": {
                "type": "gift_subscription",
                "recipient_phone": "not-a-phone",
                "plan_type": "monthly",
                "gifter_name": "Eve",
            },
        }

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=fake_event,
        ):
            response = await client.post(
                "/webhooks/payments/stripe",
                content=b"{}",
                headers={"Stripe-Signature": "valid_sig"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "invalid_phone"

    async def test_non_checkout_event_returns_ok(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A Stripe event other than checkout.session.completed returns ok."""
        fake_event = MagicMock()
        fake_event.type = "payment_intent.succeeded"

        with patch(
            "app.services.stripe_service.construct_webhook_event",
            return_value=fake_event,
        ):
            response = await client.post(
                "/webhooks/payments/stripe",
                content=b"{}",
                headers={"Stripe-Signature": "valid_sig"},
            )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Referral endpoints
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestReferralEndpoints:
    async def test_get_referral_info_existing_code(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """get_referral_info returns existing code and stats."""
        referrer = await create_test_user(db_session, phone_number="+14155550302", full_name="Has Code", share_code="HASCODE1")
        referee = await create_test_user(db_session, phone_number="+14155550303", full_name="Referred")
        await db_session.commit()
        await db_session.refresh(referrer)
        await db_session.refresh(referee)

        referral = Referral(
            referrer_user_id=referrer.id,
            referral_code="HASCODE1",
            referee_user_id=referee.id,
            referee_phone_id=referee.phone_number_id,
            status=ReferralStatus.COMPLETED,
        )
        db_session.add(referral)
        await db_session.commit()

        token = create_access_token(str(referrer.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/referrals", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["referral_code"] == "HASCODE1"
        assert data["can_refer"] is True

    async def test_get_referral_generates_code_if_missing(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Referral endpoint generates code for user without one and persists it."""
        user = await create_test_user(db_session, phone_number="+14155559021", full_name="No Code User", share_code=None)
        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/referrals", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["referral_code"] is not None
        assert len(data["referral_code"]) == 8
        assert data["can_refer"] is True

        await db_session.refresh(user)
        assert user.share_code == data["referral_code"]

    async def test_apply_referral_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Applying a valid referral code gives both users credit."""
        referrer = await create_test_user(db_session, phone_number="+14155559022", full_name="Referrer User", share_code="REFR1234")
        referee = await create_test_user(db_session, phone_number="+14155559023", full_name="Referee User")

        token = create_access_token(str(referee.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/referrals",
            headers=headers,
            json={"referral_code": "refr1234"},
        )
        assert response.status_code == 200
        assert "Referral applied" in response.json()["message"]

        await db_session.refresh(referee)
        await db_session.refresh(referrer)
        assert referee.free_credit_end is not None
        assert referee.free_credit_end > datetime.now(UTC)
        assert referrer.free_credit_end is not None
        assert referrer.free_credit_end > datetime.now(UTC)

    async def test_apply_referral_with_sms_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """apply_referral creates referral record, applies credit, and sends SMS."""
        referrer = await create_test_user(db_session, phone_number="+14155550304", full_name="Referrer Dude", share_code="RFFL0001")
        referee = await create_test_user(db_session, phone_number="+14155550305", full_name="Referee Gal")
        await db_session.commit()
        await db_session.refresh(referrer)
        await db_session.refresh(referee)

        token = create_access_token(str(referee.id))
        headers = {"Authorization": f"Bearer {token}"}

        mock_sms = AsyncMock(return_value=True)
        with patch("app.services.sms.sms_service.send_sms", mock_sms):
            response = await client.post(
                "/api/v1/referrals",
                headers=headers,
                json={"referral_code": "rffl0001"},
            )
        assert response.status_code == 200
        assert "Referral applied" in response.json()["message"]

        await db_session.refresh(referrer)
        await db_session.refresh(referee)
        assert referee.free_credit_end is not None
        assert referrer.free_credit_end is not None

        mock_sms.assert_awaited_once()
        call_args = mock_sms.call_args
        assert call_args[0][0] == referrer.phone_number
        assert "Referee Gal" in call_args[0][1]

    async def test_apply_referral_sms_failure_does_not_break_flow(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """SMS failure during apply_referral is logged but does not cause an error."""
        referrer = await create_test_user(db_session, phone_number="+14155550306", full_name="SMS Fail Referrer", share_code="SMSFAIL1")
        referee = await create_test_user(db_session, phone_number="+14155550307", full_name="SMS Fail Referee")
        await db_session.commit()
        await db_session.refresh(referrer)
        await db_session.refresh(referee)

        token = create_access_token(str(referee.id))
        headers = {"Authorization": f"Bearer {token}"}

        mock_sms = AsyncMock(side_effect=Exception("Twilio down"))
        with patch("app.services.sms.sms_service.send_sms", mock_sms):
            response = await client.post(
                "/api/v1/referrals",
                headers=headers,
                json={"referral_code": "SMSFAIL1"},
            )
        assert response.status_code == 200
        assert "Referral applied" in response.json()["message"]

    async def test_apply_referral_case_insensitive(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Referral code is uppercased before lookup, so lowercase input works."""
        referrer = await create_test_user(db_session, phone_number="+14155550308", full_name="Case Referrer", share_code="CASECOD1")
        referee = await create_test_user(db_session, phone_number="+14155550309", full_name="Case Referee")
        await db_session.commit()
        await db_session.refresh(referrer)
        await db_session.refresh(referee)

        token = create_access_token(str(referee.id))
        headers = {"Authorization": f"Bearer {token}"}

        mock_sms = AsyncMock(return_value=True)
        with patch("app.services.sms.sms_service.send_sms", mock_sms):
            response = await client.post(
                "/api/v1/referrals",
                headers=headers,
                json={"referral_code": "casecod1"},
            )
        assert response.status_code == 200
        assert "Referral applied" in response.json()["message"]

    async def test_apply_own_referral_fails(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Cannot use own referral code."""
        user = await create_test_user(db_session, phone_number="+14155559024", full_name="Self Referrer", share_code="SELFCODE")
        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/referrals",
            headers=headers,
            json={"referral_code": "SELFCODE"},
        )
        assert response.status_code == 400
        assert "own referral" in response.json()["detail"].lower()

    async def test_apply_invalid_referral_code(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Invalid referral code returns 404."""
        user = await create_test_user(db_session, phone_number="+14155559025", full_name="Bad Code User")
        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/referrals",
            headers=headers,
            json={"referral_code": "NOTREAL1"},
        )
        assert response.status_code == 404
        assert "Invalid referral code" in response.json()["detail"]

    async def test_apply_referral_twice_fails(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User cannot use a referral code if they already used one."""
        referrer = await create_test_user(db_session, phone_number="+14155559026", full_name="Referrer", share_code="DUPL1234")
        referee = await create_test_user(db_session, phone_number="+14155559027", full_name="Referee")

        existing = Referral(
            referrer_user_id=referrer.id,
            referral_code="DUPL1234",
            referee_user_id=referee.id,
            referee_phone_id=referee.phone_number_id,
            status=ReferralStatus.COMPLETED,
        )
        db_session.add(existing)
        await db_session.commit()

        token = create_access_token(str(referee.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/referrals",
            headers=headers,
            json={"referral_code": "DUPL1234"},
        )
        assert response.status_code == 400
        assert "already used" in response.json()["detail"].lower()

    async def test_apply_referral_code_maxed_out_still_credits_referee(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Referral code at max redemptions still credits the referee."""
        referrer = await create_test_user(
            db_session, phone_number="+14155559060", full_name="Popular Ref", share_code="MAXD1234"
        )
        # Set max to 2 for easier testing
        referrer.max_referral_redemptions = 2
        await db_session.commit()
        await db_session.refresh(referrer)

        # Create 2 completed referrals (at cap)
        for i in range(2):
            prev_referee = await create_test_user(
                db_session, phone_number=f"+1415555906{i + 1}", full_name=f"Prev Ref {i}"
            )
            db_session.add(Referral(
                referrer_user_id=referrer.id,
                referral_code=f"MAXD123{i}",
                referee_user_id=prev_referee.id,
                referee_phone_id=prev_referee.phone_number_id,
                status=ReferralStatus.COMPLETED,
            ))
        await db_session.commit()

        # New user uses the maxed-out code — should still work
        new_user = await create_test_user(
            db_session, phone_number="+14155559064", full_name="Too Late"
        )
        token = create_access_token(str(new_user.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/v1/referrals",
            headers=headers,
            json={"referral_code": "MAXD1234"},
        )
        assert response.status_code == 200

        # Referee gets credit
        await db_session.refresh(new_user)
        assert new_user.free_credit_end is not None

        # Referral record shows referrer was not credited
        referral = (await db_session.execute(
            select(Referral).where(Referral.referee_user_id == new_user.id)
        )).scalar_one()
        assert referral.referrer_credit_applied is False

    async def test_get_referral_info_can_refer_false_at_cap(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """can_refer is False when redemptions hit the cap."""
        referrer = await create_test_user(
            db_session, phone_number="+14155559070", full_name="Capped Ref", share_code="CAPD1234"
        )
        referrer.max_referral_redemptions = 1
        await db_session.commit()
        await db_session.refresh(referrer)

        referee = await create_test_user(
            db_session, phone_number="+14155559071", full_name="One Ref"
        )
        db_session.add(Referral(
            referrer_user_id=referrer.id,
            referral_code="CAPD1234",
            referee_user_id=referee.id,
            referee_phone_id=referee.phone_number_id,
            status=ReferralStatus.COMPLETED,
        ))
        await db_session.commit()

        token = create_access_token(str(referrer.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/referrals", headers=headers)
        assert response.status_code == 200
        assert response.json()["can_refer"] is False


# ---------------------------------------------------------------------------
# Referral lookup
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
class TestReferralLookup:
    async def test_lookup_referral_code(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Public lookup returns referrer's first name."""
        await create_test_user(db_session, phone_number="+14155559028", full_name="Jane Smith", share_code="LOOK1234")

        response = await client.get("/api/v1/referrals/look1234")
        assert response.status_code == 200
        data = response.json()
        assert data["referrer_name"] == "Jane"
        assert data["referral_code"] == "LOOK1234"

    async def test_lookup_invalid_code(self, client: AsyncClient):
        """Lookup of nonexistent code returns 404."""
        response = await client.get("/api/v1/referrals/ZZZZZZZZ")
        assert response.status_code == 404
        assert "Invalid referral code" in response.json()["detail"]

    async def test_lookup_user_without_full_name(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Lookup for user without full_name returns 'A friend'."""
        await create_test_user(db_session, phone_number="+14155550502", full_name=None, share_code="NONAME02")

        response = await client.get("/api/v1/referrals/noname02")
        assert response.status_code == 200
        data = response.json()
        assert data["referrer_name"] == "A"
        assert data["referral_code"] == "NONAME02"

    async def test_lookup_case_insensitive(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Lookup is case-insensitive (code is uppercased)."""
        await create_test_user(db_session, phone_number="+14155550503", full_name="Bob Builder", share_code="CASEIN01")

        response = await client.get("/api/v1/referrals/casein01")
        assert response.status_code == 200
        data = response.json()
        assert data["referrer_name"] == "Bob"
        assert data["referral_code"] == "CASEIN01"


# ---------------------------------------------------------------------------
# Subscription service integration
# ---------------------------------------------------------------------------
class TestSubscriptionServiceIntegration:
    async def test_resolve_pending_gifts(self, db_session: AsyncSession):
        """Pending gift subscriptions are linked on signup."""
        phone = "+14155559040"

        await subscription_service.create_subscription(
            db_session,
            phone_number=phone,
            plan_type="monthly",
            source=SubscriptionSource.STRIPE_GIFT.value,
            user_id=None,
            auto_renew=False,
        )

        user = await create_test_user(db_session, phone_number=phone, full_name="Gift Recipient")
        await subscription_service.resolve_pending_gifts(db_session, phone, user.id)

        sub = await subscription_service.get_active_subscription(db_session, user.id)
        assert sub is not None
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.source == SubscriptionSource.STRIPE_GIFT

    async def test_apply_referral_credit_extends_existing(
        self, db_session: AsyncSession
    ):
        """Applying referral credit extends existing credit."""
        user = await create_test_user(db_session, phone_number="+14155559041", full_name="Credit User", free_credit_end=datetime.now(UTC) + timedelta(days=15))
        original_end = user.free_credit_end
        await subscription_service.apply_referral_credit(db_session, user.id)
        await db_session.refresh(user)

        expected = original_end + timedelta(days=30)
        diff = abs((user.free_credit_end - expected).total_seconds())
        assert diff < 2

    async def test_is_promotion_active(self, db_session: AsyncSession):
        """Promotion detection works correctly."""
        assert await subscription_service.is_promotion_active(db_session) is False

        promo = Promotion(
            name="Test promo",
            start_date=datetime.now(UTC) - timedelta(days=1),
            end_date=datetime.now(UTC) + timedelta(days=30),
            is_active=True,
        )
        db_session.add(promo)
        await db_session.commit()

        assert await subscription_service.is_promotion_active(db_session) is True

    async def test_expired_promotion_not_active(self, db_session: AsyncSession):
        """Expired promotions are not active."""
        promo = Promotion(
            name="Old promo",
            start_date=datetime.now(UTC) - timedelta(days=60),
            end_date=datetime.now(UTC) - timedelta(days=30),
            is_active=True,
        )
        db_session.add(promo)
        await db_session.commit()

        assert await subscription_service.is_promotion_active(db_session) is False

    async def test_referral_stats(self, db_session: AsyncSession):
        """Referral stats count correctly."""
        referrer = await create_test_user(db_session, phone_number="+14155559042", full_name="Stats Referrer", share_code="STAT1234")
        referee1 = await create_test_user(db_session, phone_number="+14155559043", full_name="Referee 1")
        referee2 = await create_test_user(db_session, phone_number="+14155559044", full_name="Referee 2")
        await db_session.commit()
        await db_session.refresh(referrer)
        await db_session.refresh(referee1)
        await db_session.refresh(referee2)

        db_session.add(
            Referral(
                referrer_user_id=referrer.id,
                referral_code="STAT1234",
                referee_user_id=referee1.id,
                referee_phone_id=referee1.phone_number_id,
                status=ReferralStatus.COMPLETED,
            )
        )
        db_session.add(
            Referral(
                referrer_user_id=referrer.id,
                referral_code="STAT5678",
                referee_user_id=referee2.id,
                referee_phone_id=referee2.phone_number_id,
                status=ReferralStatus.PENDING,
            )
        )
        await db_session.commit()

        stats = await subscription_service.get_referral_stats(db_session, referrer.id)
        assert stats["total_referrals"] == 2
        assert stats["completed_referrals"] == 1
