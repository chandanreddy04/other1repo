"""Tests for the phone-keyed sponsorship-management web flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import crud_phone_number
from app.crud.sponsorship_sign_in_token import crud_sponsorship_sign_in_token
from app.services.sms import SMSResult
from tests.helpers import create_test_user


def _sms_ok() -> SMSResult:
    return SMSResult(success=True, message_id="sm_1", error=None)


@pytest.mark.asyncio
class TestPhoneFormStage:
    async def test_get_renders_phone_form(self, client: AsyncClient):
        response = await client.get("/sponsorships")
        assert response.status_code == 200
        assert "Manage your sponsorships" in response.text
        assert 'name="phone_number"' in response.text


@pytest.mark.asyncio
class TestRequestLinkStage:
    @patch(
        "app.web.routes_web_sponsorships.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
    )
    async def test_known_phone_sms_link(
        self, mock_sms, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155558101", full_name="Sponsor"
        )
        user.stripe_customer_id = "cus_real_xxx"
        await db_session.commit()
        mock_sms.return_value = _sms_ok()

        response = await client.post(
            "/sponsorships/sign-in-links",
            data={"phone_number": "+14155558101"},
        )

        assert response.status_code == 200
        assert "Check your texts" in response.text
        mock_sms.assert_awaited_once()
        sent = mock_sms.await_args.kwargs["message"]
        assert "https://" in sent or "/sponsorships/portal" in sent

    @patch(
        "app.web.routes_web_sponsorships.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
    )
    async def test_unknown_phone_does_not_send(self, mock_sms, client: AsyncClient):
        """Same response as known-phone, but no SMS fires — we don't
        oracle account existence pre-click."""
        response = await client.post(
            "/sponsorships/sign-in-links",
            data={"phone_number": "+14155558999"},
        )

        assert response.status_code == 200
        assert "Check your texts" in response.text
        mock_sms.assert_not_awaited()

    @patch(
        "app.web.routes_web_sponsorships.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
    )
    async def test_user_with_pending_stripe_id_does_not_send(
        self,
        mock_sms,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """A user who's still on the `pending:` Stripe sentinel never
        actually had a billing portal exist — don't text them a link
        that would land on 'no subs found'."""
        await create_test_user(
            db_session, phone_number="+14155558102", full_name="Pending"
        )
        # default create_test_user assigns a pending: sentinel.

        response = await client.post(
            "/sponsorships/sign-in-links",
            data={"phone_number": "+14155558102"},
        )

        assert response.status_code == 200
        assert "Check your texts" in response.text
        mock_sms.assert_not_awaited()

    @patch(
        "app.web.routes_web_sponsorships.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
    )
    async def test_purged_user_does_not_send(
        self,
        mock_sms,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        """The `purged:` sentinel means the customer link was severed
        at hard-purge — no portal is reachable."""
        user = await create_test_user(
            db_session, phone_number="+14155558103", full_name="Purged"
        )
        user.stripe_customer_id = "purged:abc"
        await db_session.commit()

        response = await client.post(
            "/sponsorships/sign-in-links",
            data={"phone_number": "+14155558103"},
        )

        assert response.status_code == 200
        mock_sms.assert_not_awaited()

    async def test_invalid_phone_re_renders_form(self, client: AsyncClient):
        response = await client.post(
            "/sponsorships/sign-in-links",
            data={"phone_number": "not a phone"},
        )
        assert response.status_code == 200
        assert "valid US phone number" in response.text


@pytest.mark.asyncio
class TestPortalStage:
    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_valid_token_redirects_to_stripe(
        self,
        mock_create,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user = await create_test_user(
            db_session, phone_number="+14155558200", full_name="Sponsor"
        )
        user.stripe_customer_id = "cus_real_yyy"
        await db_session.commit()
        mock_portal = MagicMock(url="https://billing.stripe.com/p/abc")
        mock_create.return_value = mock_portal
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )

        # GET renders the one-button page (a link previewer's fetch must
        # not open a portal); the button's POST redirects to Stripe.
        landing = await client.get(
            f"/sponsorships/portal/{row.token}", follow_redirects=False
        )
        assert landing.status_code == 200
        assert "Open billing portal" in landing.text
        mock_create.assert_not_called()

        response = await client.post(
            f"/sponsorships/portal/{row.token}", follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == "https://billing.stripe.com/p/abc"
        # Caller specified our return URL so Stripe lands the user
        # back on /sponsorships?status=saved.
        return_url = mock_create.call_args.kwargs.get("return_url")
        assert return_url is not None
        assert return_url.endswith("/sponsorships?status=saved")

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_invalid_token_routes_back_to_phone(
        self, mock_create, client: AsyncClient
    ):
        for response in (
            await client.get("/sponsorships/portal/garbage"),
            await client.post("/sponsorships/portal/garbage"),
        ):
            assert response.status_code == 200
            assert "link has expired" in response.text
        mock_create.assert_not_called()

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_valid_token_no_user_renders_not_found(
        self, mock_create, client: AsyncClient, db_session: AsyncSession
    ):
        # A token whose phone has no user (the phone row exists, e.g. a
        # deleted account's number). create_for_phone needs a phone id.
        phone, _ = await crud_phone_number.get_or_create(
            db_session, number="+14155558999"
        )
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=phone.id
        )

        response = await client.post(f"/sponsorships/portal/{row.token}")

        assert response.status_code == 200
        assert "No subscriptions found" in response.text
        mock_create.assert_not_called()

    @patch("app.web.routes_web_sponsorships.stripe_service.create_portal_session")
    async def test_stripe_failure_renders_friendly_error(
        self,
        mock_create,
        client: AsyncClient,
        db_session: AsyncSession,
    ):
        user = await create_test_user(
            db_session, phone_number="+14155558201", full_name="Sponsor"
        )
        user.stripe_customer_id = "cus_real_zzz"
        await db_session.commit()
        mock_create.side_effect = RuntimeError("stripe down")
        row = await crud_sponsorship_sign_in_token.create_for_phone(
            db_session, phone_number_id=user.phone_number_id
        )

        response = await client.post(f"/sponsorships/portal/{row.token}")

        assert response.status_code == 200
        # HTML-escaped apostrophe.
        assert "couldn" in response.text and "open the billing portal" in response.text
        # The button is re-rendered so the retry is one tap.
        assert "Open billing portal" in response.text


@pytest.mark.asyncio
class TestSavedStage:
    async def test_renders_confirmation(self, client: AsyncClient):
        response = await client.get("/sponsorships?status=saved")
        assert response.status_code == 200
        assert "Changes saved" in response.text
