"""Tests for the unified /sponsorships web flow (commit 9: one sponsorship
flow — owner decision 2026-09-23, sponsorship.html states + the phone-keyed
/sponsorships management page).

Related: app/web/routes_web.py (GET /sponsorships/new, POST /sponsorships,
GET/POST /sponsorships/{share_code}[/checkout]), app/web/routes_web_sponsorships.py
(GET/POST /sponsorships[/sign-in-links|/portal]), app/web/templates/sponsorship.html.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.sms import SMSResult
from tests.helpers import create_test_user


def _sms_ok() -> SMSResult:
    return SMSResult(success=True, message_id="sm_1", error=None)


@pytest.mark.asyncio
class TestEnterRecipientState:
    async def test_sponsorships_new_renders_enter_recipient(self, client: AsyncClient):
        response = await client.get("/sponsorships/new")
        assert response.status_code == 200
        assert "Recipient's Phone Number" in response.text
        assert 'action="/sponsorships"' in response.text


@pytest.mark.asyncio
class TestKnownRecipientState:
    async def test_renders_first_name_not_phone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(
            db_session,
            phone_number="+14155590900",
            full_name="Jamie Rivera",
            share_code="SPONS001",
        )

        response = await client.get("/sponsorships/SPONS001")

        assert response.status_code == 200
        assert "Jamie" in response.text
        assert "+14155590900" not in response.text
        assert "4155590900" not in response.text

    async def test_lookup_is_case_insensitive(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(
            db_session,
            phone_number="+14155590901",
            full_name="Bo Lin",
            share_code="SPONS002",
        )
        response = await client.get("/sponsorships/spons002")
        assert response.status_code == 200
        assert "Bo" in response.text


@pytest.mark.asyncio
class TestNotFoundState:
    async def test_unknown_code_renders_not_found(self, client: AsyncClient):
        response = await client.get("/sponsorships/NOPE9999")
        assert response.status_code == 404
        assert "no longer valid" in response.text


@pytest.mark.asyncio
class TestStatusStates:
    """?status=success / ?status=canceled render directly — no Stripe call."""

    async def test_generic_success(self, client: AsyncClient):
        response = await client.get("/sponsorships/new?status=success")
        assert response.status_code == 200
        assert "Sponsorship sent" in response.text
        assert "subscription is ready" not in response.text

    async def test_generic_canceled(self, client: AsyncClient):
        response = await client.get("/sponsorships/new?status=canceled")
        assert response.status_code == 200
        assert "Payment Cancelled" in response.text

    async def test_personalized_success_looks_name_up_server_side(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(
            db_session,
            phone_number="+14155590904",
            full_name="Jamie Rivera",
            share_code="SPONS004",
        )
        response = await client.get("/sponsorships/spons004?status=success")
        assert response.status_code == 200
        assert "Sponsorship sent" in response.text
        assert "Jamie's subscription is ready" in response.text

    async def test_personalized_success_unknown_code_shows_no_name(
        self, client: AsyncClient
    ):
        response = await client.get("/sponsorships/NOPE9999?status=success")
        assert response.status_code == 200
        assert "Sponsorship sent" in response.text
        assert "subscription is ready" not in response.text

    @pytest.mark.parametrize(
        "path",
        [
            "/sponsorships/new?status=success&phone=%2B14155551234&name=Mallory",
            "/sponsorships/NOPE9999?status=success&phone=%2B14155551234&name=Mallory",
        ],
    )
    async def test_success_never_echoes_phone_or_name_query_params(
        self, client: AsyncClient, path: str
    ):
        """Stripe-stored success URLs carry no PII, and the page must not
        render attacker-supplied text from the query string either."""
        response = await client.get(path)
        assert response.status_code == 200
        assert "Sponsorship sent" in response.text
        assert "Mallory" not in response.text
        assert "4155551234" not in response.text

    async def test_personalized_canceled(self, client: AsyncClient):
        response = await client.get(
            "/sponsorships/SPONS001?status=canceled&back=/sponsorships/SPONS001"
        )
        assert response.status_code == 200
        assert "Payment Cancelled" in response.text
        assert "/sponsorships/SPONS001" in response.text

    async def test_canceled_back_default_is_safe_next_path(self, client: AsyncClient):
        """An unsafe `back` falls through safe_next_path's default rather
        than being echoed verbatim."""
        response = await client.get(
            "/sponsorships/new?status=canceled&back=https://evil.example/phish"
        )
        assert response.status_code == 200
        assert "evil.example" not in response.text
        assert "/sponsorships/new" in response.text


@pytest.mark.asyncio
class TestGenericCheckoutStripeUrls:
    @patch("app.services.stripe_service.create_gift_checkout_session")
    async def test_success_and_cancel_urls_point_at_new_status(
        self, mock_checkout, client: AsyncClient
    ):
        mock_checkout.return_value = MagicMock(url="https://checkout.stripe.com/abc")

        response = await client.post(
            "/sponsorships",
            data={
                "recipient_phone": "+14155551234",
                "gifter_phone": "+14155555678",
                "plan_type": "monthly",
            },
            follow_redirects=False,
        )

        assert response.status_code == 303
        kwargs = mock_checkout.call_args.kwargs
        assert kwargs["success_url"].endswith("/sponsorships/new?status=success")
        assert kwargs["cancel_url"].endswith("/sponsorships/new?status=canceled")
        for url in (kwargs["success_url"], kwargs["cancel_url"]):
            assert "phone" not in url
            assert "4155551234" not in url


@pytest.mark.asyncio
class TestPersonalizedCheckoutStripeUrls:
    @patch("app.services.stripe_service.create_gift_checkout_session")
    async def test_success_and_cancel_urls_point_at_share_code_status(
        self, mock_checkout, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(
            db_session,
            phone_number="+14155590902",
            full_name="Robin Kim",
            share_code="SPONS003",
        )
        mock_checkout.return_value = MagicMock(url="https://checkout.stripe.com/xyz")

        # Lower-case path code: the URLs must use the stored share code.
        response = await client.post(
            "/sponsorships/spons003/checkout",
            data={"gifter_phone": "+14155555678", "plan_type": "annual"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        kwargs = mock_checkout.call_args.kwargs
        assert kwargs["success_url"].endswith("/sponsorships/SPONS003?status=success")
        assert kwargs["cancel_url"].endswith(
            "/sponsorships/SPONS003?status=canceled&back=/sponsorships/SPONS003"
        )
        for url in (kwargs["success_url"], kwargs["cancel_url"]):
            assert "Robin" not in url
            assert "name=" not in url
            assert "4155590902" not in url


@pytest.mark.asyncio
class TestOtpFragmentHardening:
    @patch(
        "app.web.routes_htmx_sponsorships.otp_service.verify_otp",
        new_callable=AsyncMock,
    )
    async def test_verify_failure_never_echoes_quote_bearing_phone(
        self, mock_verify, client: AsyncClient
    ):
        """A `"`-bearing phone must not reach the hx-vals JSON (it would
        break out and inject keys) — it fails E164 validation first."""
        evil = '+1415", "force_resend": true, "x": "'
        response = await client.post(
            "/htmx/sponsorships/SPONS001/verify-otp",
            data={"phone_number": evil, "otp_code": "123456"},
        )
        assert response.status_code == 200
        assert "force_resend" not in response.text
        assert "Please enter a valid phone number" in response.text
        mock_verify.assert_not_awaited()

    @patch(
        "app.web.routes_htmx_sponsorships.otp_service.verify_otp",
        new_callable=AsyncMock,
    )
    async def test_verify_failure_renders_hx_vals_as_valid_json(
        self, mock_verify, client: AsyncClient
    ):
        import html
        import json
        import re

        mock_verify.return_value = (False, "Invalid code")
        response = await client.post(
            "/htmx/sponsorships/SPONS001/verify-otp",
            data={"phone_number": "+14155551234", "otp_code": "000000"},
        )
        assert response.status_code == 200
        vals = re.findall(r"hx-vals='([^']*)'", response.text)
        assert vals
        for raw in vals:
            parsed = json.loads(html.unescape(raw))
            assert parsed["phone_number"] == "+14155551234"
            assert parsed["is_resend"] is True

    @patch(
        "app.web.routes_htmx_sponsorships.otp_service.get_resend_wait_seconds",
        new_callable=AsyncMock,
    )
    async def test_resend_timer_script_is_scoped(self, mock_wait, client: AsyncClient):
        """The timer script is re-run on every htmx swap; top-level
        let/const would throw on the second run, so it must be an IIFE."""
        mock_wait.return_value = 30
        response = await client.post(
            "/htmx/sponsorships/SPONS001/request-otp",
            data={
                "phone_number": "+14155551234",
                "current_phone": "+14155551234",
            },
        )
        assert response.status_code == 200
        body = response.text
        assert "let seconds = 30;" in body
        script = body[body.rindex("<script>", 0, body.index("let seconds")) :]
        assert script.index("(function () {") < script.index("let seconds")


@pytest.mark.asyncio
class TestSavedState:
    async def test_sponsorships_status_saved_renders_saved_state(
        self, client: AsyncClient
    ):
        response = await client.get("/sponsorships?status=saved")
        assert response.status_code == 200
        assert "Changes saved" in response.text


@pytest.mark.asyncio
class TestSignInLinkSmsUnchangedExceptPath:
    @patch(
        "app.web.routes_web_sponsorships.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
    )
    async def test_sms_body_matches_old_wording_new_path(
        self, mock_sms, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155590903", full_name="Sponsor"
        )
        user.stripe_customer_id = "cus_real_abc"
        await db_session.commit()
        mock_sms.return_value = _sms_ok()

        response = await client.post(
            "/sponsorships/sign-in-links",
            data={"phone_number": "+14155590903"},
        )

        assert response.status_code == 200
        mock_sms.assert_awaited_once()
        sent = mock_sms.await_args.kwargs["message"]

        # Same wording as the old /sponsor/request SMS, byte-identical
        # except the URL: /sponsor/portal?token= -> (2026-09-23)
        # /sponsorships/portal?token= -> (2026-09-27) the short link
        # {SHORT_DOMAIN}/s/p/{12-char one-time token}.
        prefix = "Manage your Made It Home sponsorships: "
        suffix = " (link expires in 10 minutes)"
        assert sent.startswith(prefix)
        assert sent.endswith(suffix)
        link = sent[len(prefix) : -len(suffix)]
        short_prefix = f"{settings.SHORT_DOMAIN}/s/p/"
        assert link.startswith(short_prefix)
        assert len(link[len(short_prefix) :]) == 12
        assert "/sponsor/portal" not in link


@pytest.mark.asyncio
class TestShortLinkRedirectsToSponsorships:
    async def test_s_short_link_redirects_uppercased(self, client: AsyncClient):
        response = await client.get("/s/spons001", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == "/sponsorships/SPONS001"


@pytest.mark.asyncio
class TestOldGiftAndSponsorRoutesGone:
    async def test_gift_gone(self, client: AsyncClient):
        response = await client.get("/gift")
        assert response.status_code == 404

    async def test_gift_share_code_gone(self, client: AsyncClient):
        response = await client.get("/gift/SPONS001")
        assert response.status_code == 404

    async def test_sponsor_gone(self, client: AsyncClient):
        response = await client.get("/sponsor")
        assert response.status_code == 404

    async def test_sponsor_done_gone(self, client: AsyncClient):
        response = await client.get("/sponsor/done")
        assert response.status_code == 404
