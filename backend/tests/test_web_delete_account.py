"""Tests for the public web /account/delete flow.

Covers the four-stage state machine in routes_web_delete.py:
phone form → OTP verify → confirmation + typed gate → success.

Related: app/web/routes_web_delete.py, app/services/account_deletion.py
         docs/account-deletion-plan.md (web deletion path)
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.account_deletion import (
    decode_deletion_token,
    mint_deletion_token,
)
from app.web.routes_web_delete import CONFIRM_PHRASE, DELETION_COOKIE_NAME
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestPhoneFormStage:
    async def test_get_renders_phone_form(self, client: AsyncClient):
        response = await client.get("/account/delete")
        assert response.status_code == 200
        body = response.text
        assert "Delete your account" in body
        assert 'name="phone_number"' in body
        # The OTP form must NOT be rendered before phone submit.
        assert 'name="otp_code"' not in body


@pytest.mark.asyncio
class TestStartStage:
    @patch("app.web.routes_web_delete.otp_service.send_otp", new_callable=AsyncMock)
    async def test_existing_user_advances_to_otp(
        self, mock_send, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(db_session, phone_number="+14155551700")

        response = await client.post(
            "/account/delete/codes",
            data={"phone_number": "(415) 555-1700"},
        )

        assert response.status_code == 200
        assert 'name="otp_code"' in response.text
        mock_send.assert_awaited_once()

    @patch("app.web.routes_web_delete.otp_service.send_otp", new_callable=AsyncMock)
    async def test_nonexistent_number_does_not_reveal(
        self, mock_send, client: AsyncClient
    ):
        """Don't oracle whether a phone is registered before OTP — same
        pattern as a password reset on most services."""
        response = await client.post(
            "/account/delete/codes",
            data={"phone_number": "+14155558999"},
        )

        assert response.status_code == 200
        assert 'name="otp_code"' in response.text
        # No OTP actually sent for unknown numbers.
        mock_send.assert_not_awaited()

    async def test_invalid_phone_re_renders_phone_form(self, client: AsyncClient):
        response = await client.post(
            "/account/delete/codes",
            data={"phone_number": "not a phone"},
        )

        assert response.status_code == 200
        assert "valid US phone number" in response.text
        assert 'name="otp_code"' not in response.text


@pytest.mark.asyncio
class TestVerifyStage:
    @patch("app.web.routes_web_delete.otp_service.verify_otp", new_callable=AsyncMock)
    async def test_bad_otp_re_renders_otp_form(
        self, mock_verify, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(db_session, phone_number="+14155551701")
        mock_verify.return_value = (False, "Invalid code")

        response = await client.post(
            "/account/delete/verifications",
            data={"phone_number": "+14155551701", "otp_code": "000000"},
        )

        assert response.status_code == 200
        assert "Invalid code" in response.text
        assert 'name="otp_code"' in response.text
        assert DELETION_COOKIE_NAME not in response.cookies

    @patch("app.web.routes_web_delete.otp_service.verify_otp", new_callable=AsyncMock)
    async def test_good_otp_sets_deletion_cookie_and_renders_confirm(
        self, mock_verify, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155551702", full_name="Real Name"
        )
        mock_verify.return_value = (True, "ok")

        response = await client.post(
            "/account/delete/verifications",
            data={"phone_number": "+14155551702", "otp_code": "123456"},
        )

        assert response.status_code == 200
        assert "Real Name" in response.text
        assert "Type" in response.text and CONFIRM_PHRASE in response.text
        # Cookie should carry a valid deletion token for THIS user.
        assert DELETION_COOKIE_NAME in response.cookies
        token = response.cookies[DELETION_COOKIE_NAME]
        assert decode_deletion_token(token) == user.id


@pytest.mark.asyncio
class TestConfirmStage:
    @patch(
        "app.web.routes_web_delete.account_deletion.delete_user_account",
        new_callable=AsyncMock,
    )
    async def test_happy_path_calls_orchestrator_and_clears_cookie(
        self, mock_delete, client: AsyncClient, db_session: AsyncSession
    ):
        from datetime import UTC, datetime

        user = await create_test_user(db_session, phone_number="+14155551703")
        mock_delete.return_value = datetime.now(UTC)
        token = mint_deletion_token(user.id)
        client.cookies.set(DELETION_COOKIE_NAME, token)

        response = await client.post(
            "/account/delete/confirmations",
            data={"confirm_phrase": CONFIRM_PHRASE},
        )

        assert response.status_code == 200
        assert "Account deletion scheduled" in response.text
        mock_delete.assert_awaited_once()
        # Cookie cleared by the success response.
        cookie_header = response.headers.get("set-cookie", "")
        assert DELETION_COOKIE_NAME in cookie_header
        assert "Max-Age=0" in cookie_header or "expires=" in cookie_header.lower()
        # Reset client cookies so other tests don't see this.
        client.cookies.delete(DELETION_COOKIE_NAME)

    async def test_missing_cookie_routes_back_to_phone(self, client: AsyncClient):
        response = await client.post(
            "/account/delete/confirmations",
            data={"confirm_phrase": CONFIRM_PHRASE},
        )

        assert response.status_code == 200
        assert "Your session expired" in response.text
        assert 'name="phone_number"' in response.text

    async def test_tampered_cookie_routes_back_to_phone(self, client: AsyncClient):
        client.cookies.set(DELETION_COOKIE_NAME, "not.a.jwt")

        response = await client.post(
            "/account/delete/confirmations",
            data={"confirm_phrase": CONFIRM_PHRASE},
        )

        assert response.status_code == 200
        assert "Your session expired" in response.text
        client.cookies.delete(DELETION_COOKIE_NAME)

    async def test_wrong_phrase_re_prompts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155551704")
        token = mint_deletion_token(user.id)
        client.cookies.set(DELETION_COOKIE_NAME, token)

        response = await client.post(
            "/account/delete/confirmations",
            data={"confirm_phrase": "DELETE NOW"},
        )

        assert response.status_code == 200
        assert "Please type" in response.text
        client.cookies.delete(DELETION_COOKIE_NAME)

    async def test_cookie_for_nonexistent_user_returns_success(
        self, client: AsyncClient
    ):
        """Edge case: the token was minted for a user that's been removed
        between verify and confirm. There's nothing left to delete — show
        the success page rather than erroring."""
        token = mint_deletion_token(uuid.uuid4())
        client.cookies.set(DELETION_COOKIE_NAME, token)

        response = await client.post(
            "/account/delete/confirmations",
            data={"confirm_phrase": CONFIRM_PHRASE},
        )

        assert response.status_code == 200
        assert "Account deletion scheduled" in response.text or (
            "deleted" in response.text
        )
        client.cookies.delete(DELETION_COOKIE_NAME)
