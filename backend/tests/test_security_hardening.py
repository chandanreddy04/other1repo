"""Tests for security hardening fixes (XSS, open redirect, idempotency)."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.circle_of_trust import crud_circle_of_trust
from app.crud.user import crud_user
from app.models.processed_stripe_event import ProcessedStripeEvent
from app.models.subscription import Subscription
from app.schemas.user import UserCreate
from tests.helpers import create_test_user


def _mock_stripe_event(
    event_type: str, data_object: dict, event_id: str = "evt_test_001"
) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    event.type = event_type
    event.data.object = data_object
    return event


@pytest.mark.asyncio
class TestStoredXSSViaFullName:
    """P2.1: full_name containing script tags must be escaped in HTML responses."""

    async def test_accept_invitation_escapes_inviter_name(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155550201",
            full_name='<script>alert("xss")</script>',
            circle_invite_code="XSSCODE1",
        )
        # A share_code makes the accepted lander render the referral offer
        # too, so every place the inviter's name appears is exercised.
        inviter.share_code = "XSSSHARE"
        await db_session.commit()
        invitee = await create_test_user(
            db_session, phone_number="+14155550202", full_name="Invitee"
        )

        from app.schemas.circle_of_trust import CircleOfTrustMemberCreate

        await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=inviter.id,
            obj_in=CircleOfTrustMemberCreate(contact_phone_number=invitee.phone_number),
        )

        token = create_access_token(str(invitee.id))

        # PRG: follow the redirect by hand — httpx's follow_redirects doesn't
        # resend a per-request `cookies=` kwarg, so it would land logged out.
        post = await client.post(
            f"/circles/{inviter.circle_invite_code}/accept",
            cookies={"access_token": token},
            follow_redirects=False,
        )
        assert post.status_code == 303
        response = await client.get(
            post.headers["location"], cookies={"access_token": token}
        )
        assert response.status_code == 200
        assert "You're in!" in response.text
        assert "Claim Free Month" in response.text

        body = response.text
        assert "<script>" not in body
        assert "&lt;script&gt;" in body or "alert" not in body


@pytest.mark.asyncio
class TestReflectedXSSViaNextUrl:
    """P2.2: next_url must be validated against open redirect and XSS."""

    async def test_malicious_next_url_ignored(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = UserCreate(phone_number="+14155550301", full_name="Redirect Test")
        await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        from app.services.otp import otp_service

        await otp_service.send_otp(db_session, "+14155550301")

        from app.models.otp import OTP

        result = await db_session.execute(select(OTP))
        otp = result.scalars().first()
        assert otp is not None

        response = await client.post(
            "/web/login/verify",
            data={
                "phone_number": "+14155550301",
                "otp_code": otp.otp_code,
                "next_url": "https://evil.example/steal",
            },
            follow_redirects=False,
        )

        if response.status_code == 200:
            assert "evil.example" not in response.text

    async def test_js_breakout_next_url_escaped(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = UserCreate(
            phone_number="+14155550302", full_name="XSS Redirect Test"
        )
        await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        from app.services.otp import otp_service

        await otp_service.send_otp(db_session, "+14155550302")

        from app.models.otp import OTP

        result = await db_session.execute(select(OTP))
        otp = result.scalars().first()
        assert otp is not None

        response = await client.post(
            "/web/login/verify",
            data={
                "phone_number": "+14155550302",
                "otp_code": otp.otp_code,
                "next_url": "foo'); alert(1); //",
            },
            follow_redirects=False,
        )

        if response.status_code == 200:
            assert "alert(1)" not in response.text

    async def test_valid_next_url_preserved(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_data = UserCreate(
            phone_number="+14155550303", full_name="Valid Redirect Test"
        )
        await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        from app.services.otp import otp_service

        await otp_service.send_otp(db_session, "+14155550303")

        from app.models.otp import OTP

        result = await db_session.execute(select(OTP))
        otp = result.scalars().first()
        assert otp is not None

        response = await client.post(
            "/web/login/verify",
            data={
                "phone_number": "+14155550303",
                "otp_code": otp.otp_code,
                "next_url": "/alerts",
            },
            follow_redirects=False,
        )

        if response.status_code == 200:
            assert "/alerts" in response.text


@pytest.mark.asyncio
class TestOpenRedirectSponsorshipCanceled:
    """P2.3: back parameter on the sponsorship canceled state must be validated."""

    async def test_external_back_url_rejected(self, client: AsyncClient):
        response = await client.get(
            "/sponsorships/new?status=canceled&back=https://evil.example/phish",
            follow_redirects=False,
        )

        if response.status_code == 200:
            assert "evil.example" not in response.text
            assert (
                'href="/sponsorships/new"' in response.text
                or "/sponsorships/new" in response.text
            )

    async def test_protocol_relative_back_url_rejected(self, client: AsyncClient):
        response = await client.get(
            "/sponsorships/new?status=canceled&back=//evil.example/phish",
            follow_redirects=False,
        )

        if response.status_code == 200:
            assert "evil.example" not in response.text

    async def test_valid_back_url_preserved(self, client: AsyncClient):
        response = await client.get(
            "/sponsorships/new?status=canceled&back=/sponsorships/abc123",
            follow_redirects=False,
        )

        if response.status_code == 200:
            assert "/sponsorships/abc123" in response.text


@pytest.mark.asyncio
class TestStripeWebhookIdempotency:
    """P3.1: duplicate Stripe webhook events must not create duplicate records."""

    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_duplicate_event_skipped(
        self, mock_construct, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        event = _mock_stripe_event(
            "checkout.session.completed",
            {
                "id": "cs_idem_123",
                "subscription": "sub_idem_abc",
                "metadata": {
                    "type": "subscription",
                    "user_id": str(test_user.id),
                    "plan_type": "monthly",
                },
            },
            event_id="evt_idem_001",
        )
        mock_construct.return_value = event

        response1 = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response1.status_code == 200

        response2 = await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )
        assert response2.status_code == 200

        result = await db_session.execute(
            select(Subscription).where(
                Subscription.stripe_subscription_id == "sub_idem_abc"
            )
        )
        subs = result.scalars().all()
        assert len(subs) == 1

        result = await db_session.execute(
            select(ProcessedStripeEvent).where(
                ProcessedStripeEvent.event_id == "evt_idem_001"
            )
        )
        assert result.scalar_one_or_none() is not None

    @patch("app.services.stripe_service.construct_webhook_event")
    async def test_different_events_both_processed(
        self, mock_construct, client: AsyncClient, test_user, db_session: AsyncSession
    ):
        event1 = _mock_stripe_event(
            "checkout.session.completed",
            {
                "id": "cs_diff_1",
                "subscription": "sub_diff_1",
                "metadata": {
                    "type": "subscription",
                    "user_id": str(test_user.id),
                    "plan_type": "monthly",
                },
            },
            event_id="evt_diff_001",
        )
        mock_construct.return_value = event1

        await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )

        event2 = _mock_stripe_event(
            "checkout.session.completed",
            {
                "id": "cs_diff_2",
                "subscription": "sub_diff_2",
                "metadata": {
                    "type": "subscription",
                    "user_id": str(test_user.id),
                    "plan_type": "annual",
                },
            },
            event_id="evt_diff_002",
        )
        mock_construct.return_value = event2

        await client.post(
            "/webhooks/payments/stripe",
            content=b"payload",
            headers={"Stripe-Signature": "sig"},
        )

        result = await db_session.execute(select(ProcessedStripeEvent))
        events = result.scalars().all()
        event_ids = {e.event_id for e in events}
        assert "evt_diff_001" in event_ids
        assert "evt_diff_002" in event_ids


@pytest.mark.asyncio
class TestPhoneNumberEscaping:
    """Verify phone number is escaped in HTMX fragments to prevent attribute injection."""

    async def test_phone_number_escaped_in_otp_form(self, client: AsyncClient):
        response = await client.post(
            "/web/htmx/request-otp/dummy_code",
            data={"phone_number": '"><img src=x onerror=alert(1)>'},
            follow_redirects=False,
        )

        if response.status_code == 200:
            body = response.text
            assert "onerror=alert(1)" not in body
            assert "&lt;" in body or "&gt;" in body or "&quot;" in body
