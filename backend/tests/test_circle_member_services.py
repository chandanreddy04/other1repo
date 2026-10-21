"""Circle-member accept coverage (service level).

Re-homed here from the mobile API tests (formerly test_accept_invitation_by_code.py,
which covered the code-based accept endpoint; parts of `test_circle_welcome_sms.py`)
after the 2026-09-22 owner decision removed those mobile accept endpoints (no
in-app caller — Circle members use mobile web only). The service itself is unchanged
and still backs the web accept flow (`POST /circles/{code}/accept`,
`app/web/routes_web.py::circle_invite_accept`); these tests exercise it
directly so the accept/reject invariants survive independent of any HTTP
surface.

The web lander's other Circle-member actions (decline, leave, the
referral-offer-on-accept) moved to tests/test_web_circles.py 2026-09-23,
alongside the rest of the /circles page coverage — they used to live here
as cookie-auth htmx routes in app/web/routes_htmx_profile.py (the whole
module, and the web dashboard, were deleted 2026-09-23); those routes went when /circle/{code} + /invitations became the REST-shaped
/circles page and /circles/{code}/accept|decline|leave routes.

Related: app/services/circle_invitations.py, tests/test_web_circles.py,
tests/test_no_app_contact_flows.py (the web-lander accept coverage).
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.circle_of_trust import crud_circle_of_trust
from app.models.circle_of_trust import ContactStatus
from app.schemas.circle_of_trust import CircleOfTrustMemberCreate
from app.services import circle_invitations
from tests.helpers import create_test_user


async def _pending_invite(db: AsyncSession, inviter_phone: str, contact_phone: str):
    inviter = await create_test_user(
        db, phone_number=inviter_phone, full_name="Ivy Inviter"
    )
    accepter = await create_test_user(
        db, phone_number=contact_phone, full_name="Cody Contact"
    )
    await crud_circle_of_trust.create_by_phone(
        db,
        user_id=inviter.id,
        obj_in=CircleOfTrustMemberCreate(contact_phone_number=accepter.phone_number),
    )
    return inviter, accepter


@pytest.mark.asyncio
class TestAcceptCircleInvite:
    async def test_accept_activates_membership_and_sends_welcome_sms(
        self, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155580001", "+14155580002"
        )
        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ) as mock_welcome:
            member = await circle_invitations.accept_circle_invite(
                db_session, inviter=inviter, accepter=accepter
            )
        assert member.status == ContactStatus.ACTIVE
        mock_welcome.assert_awaited_once_with(accepter=accepter, inviter=inviter)

    async def test_self_accept_is_rejected(self, db_session: AsyncSession):
        inviter, _ = await _pending_invite(db_session, "+14155580003", "+14155580004")
        with pytest.raises(circle_invitations.SelfAcceptError):
            await circle_invitations.accept_circle_invite(
                db_session, inviter=inviter, accepter=inviter
            )

    async def test_no_pending_invite_for_pair_is_rejected(
        self, db_session: AsyncSession
    ):
        # Inviter has a pending invite, but not for this accepter's phone.
        inviter, _ = await _pending_invite(db_session, "+14155580005", "+14155580006")
        stranger = await create_test_user(
            db_session, phone_number="+14155580007", full_name="Stranger"
        )
        with pytest.raises(circle_invitations.NoPendingInviteError):
            await circle_invitations.accept_circle_invite(
                db_session, inviter=inviter, accepter=stranger
            )

    async def test_reaccepting_an_active_membership_is_rejected_and_does_not_resend(
        self, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155580008", "+14155580009"
        )
        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ) as mock_welcome:
            await circle_invitations.accept_circle_invite(
                db_session, inviter=inviter, accepter=accepter
            )
            mock_welcome.reset_mock()

            with pytest.raises(circle_invitations.NoPendingInviteError):
                await circle_invitations.accept_circle_invite(
                    db_session, inviter=inviter, accepter=accepter
                )
            mock_welcome.assert_not_called()

    async def test_welcome_sms_failure_does_not_block_acceptance(
        self, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155580010", "+14155580011"
        )
        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
            side_effect=RuntimeError("SMS down"),
        ):
            member = await circle_invitations.accept_circle_invite(
                db_session, inviter=inviter, accepter=accepter
            )
        assert member.status == ContactStatus.ACTIVE
