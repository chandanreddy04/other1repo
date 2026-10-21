"""Tests for post-acceptance circle welcome SMS (privacy plan 2.3).

The mobile API accept endpoint (`POST /circle-of-trust/invitations/{id}/accept`)
was removed 2026-09-22 (no in-app caller — Circle members use mobile web
only); its welcome-SMS coverage (success, SMS-failure-doesn't-block-accept,
re-accept-doesn't-resend) is re-homed at the service level in
`tests/test_circle_member_services.py`. The web lander's accept route below
(`POST /circles/{code}/accept`, app/web/routes_web.py::circle_invite_accept,
renamed 2026-09-23 from the dashboard's htmx accept route) is a separate
surface and keeps its own coverage here.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.circle_of_trust import crud_circle_of_trust
from app.schemas.circle_of_trust import CircleOfTrustMemberCreate
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestCircleWelcomeSMS:
    async def test_web_accept_sends_welcome_sms(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155550307",
            full_name="Morgan",
            circle_invite_code="WELCOME1",
        )
        accepter = await create_test_user(
            db_session, phone_number="+14155550308", full_name="Taylor"
        )

        await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=inviter.id,
            obj_in=CircleOfTrustMemberCreate(
                contact_phone_number=accepter.phone_number
            ),
        )

        token = create_access_token(str(accepter.id))

        with patch("app.services.notification_helpers.sms_service") as mock_sms:
            mock_sms.send_sms = AsyncMock(return_value=AsyncMock(success=True))

            # PRG: follow the redirect by hand — httpx's follow_redirects
            # doesn't resend a per-request `cookies=` kwarg.
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

            mock_sms.send_sms.assert_called_once()
            call_kwargs = mock_sms.send_sms.call_args
            assert "Morgan" in str(call_kwargs)
