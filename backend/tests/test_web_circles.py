"""GET /circles and POST /circles/{code}/accept|decline|leave.

Circle members use mobile web only (owner decision 2026-09-22); this is
their page for managing Circle invitations and memberships — renamed from
GET /invitations, with the invite lander folded in from GET /circle/{code}
+ POST /circle/{code}/accept (owner decision 2026-09-23, REST-shaped
vocabulary: Circle / Circle member / Circle invitation).

Covers:
- /circles lists the viewer's pending invitations and ACTIVE memberships
  (matched by their own phone) — never the circles they OWN, which is what
  the old page's "active circles" section wrongly showed
  (crud_circle_of_trust.get_user_contacts, /crud/circle_of_trust.py:31-39).
- accept activates the membership, sends the welcome SMS, and offers the
  inviter's referral code only when the accepter has never redeemed one
  (referral_service.referral_offer_for).
- decline / leave soft-remove (REMOVED) — leave never hard-deletes, unlike
  the old htmx handler it replaces.
- every POST guards current_user is None (redirect to /login?next=...);
  an owner can't decline/leave their own circle via their own code.
- the lander is web-only (no install-the-app path, no Smart App Banner),
  the referral claim swaps only the offer box (the DND guidance stays),
  and the claim endpoint answers a logged-out tap with an error fragment.
- GET /circles renders pending invitations / memberships on a FRESH
  session (inviters preloaded — a lazy `member.user` 500'd it).

Related: app/web/routes_web.py (circles_page, circle_invite_page,
circle_invite_accept/decline/leave), app/services/circle_invitations.py,
app/services/referral.py, tests/test_no_app_contact_flows.py (the invite
lander's GET/logged-out-accept states).
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.circle_of_trust import crud_circle_of_trust
from app.models.circle_of_trust import ContactStatus
from app.models.subscription import Referral
from app.models.user import User
from app.schemas.circle_of_trust import CircleOfTrustMemberCreate
from app.services import circle_invitations
from app.services.referral import referral_service
from tests.helpers import create_test_user


def _cookies(user: User) -> dict:
    return {"access_token": create_access_token(str(user.id))}


async def _post_and_follow(client: AsyncClient, url: str, *, cookies: dict):
    """POST then follow a single 3xx redirect, both carrying `cookies`.

    httpx's own `follow_redirects=True` does NOT resend a per-request
    `cookies=` kwarg on the redirected request (it's request-scoped, not
    added to the client's cookie jar) — so a redirect to a cookie-gated
    page would come back logged-out. Every /circles POST is PRG, so tests
    that need to see the redirected page do the hop explicitly.
    """
    resp = await client.post(url, cookies=cookies, follow_redirects=False)
    assert resp.status_code == 303
    return await client.get(resp.headers["location"], cookies=cookies)


async def _pending_invite(
    db: AsyncSession, inviter_phone: str, contact_phone: str, *, code: str
):
    inviter = await create_test_user(
        db, phone_number=inviter_phone, full_name="Ivy Inviter", circle_invite_code=code
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


async def _active_member(
    db: AsyncSession, inviter_phone: str, contact_phone: str, *, code: str
):
    inviter, member = await _pending_invite(db, inviter_phone, contact_phone, code=code)
    row = await circle_invitations.get_member_for_accepter(
        db, inviter=inviter, accepter=member
    )
    await crud_circle_of_trust.accept_invitation(db, contact=row)
    return inviter, member


@pytest.mark.asyncio
class TestCirclesPage:
    async def test_lists_pending_invitations_and_active_memberships_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        viewer = await create_test_user(
            db_session, phone_number="+14155597001", full_name="Viv Viewer"
        )
        # B invites the viewer — PENDING, should show under invitations.
        inviter_b = await create_test_user(
            db_session,
            phone_number="+14155597002",
            full_name="Bob Backup",
            circle_invite_code="CIRCB001",
        )
        await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=inviter_b.id,
            obj_in=CircleOfTrustMemberCreate(contact_phone_number=viewer.phone_number),
        )
        # C's circle: viewer is an ACTIVE member — should show under memberships.
        inviter_c = await create_test_user(
            db_session,
            phone_number="+14155597003",
            full_name="Cara Circle",
            circle_invite_code="CIRCC001",
        )
        row_c = await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=inviter_c.id,
            obj_in=CircleOfTrustMemberCreate(contact_phone_number=viewer.phone_number),
        )
        await crud_circle_of_trust.accept_invitation(db_session, contact=row_c)
        # The viewer's OWN circle (they're the inviter/owner) — must NOT
        # appear anywhere on this page, pending or active.
        owned_contact = await create_test_user(
            db_session, phone_number="+14155597004", full_name="Owned Contact"
        )
        row_owned = await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=viewer.id,
            obj_in=CircleOfTrustMemberCreate(
                contact_phone_number=owned_contact.phone_number
            ),
        )
        await crud_circle_of_trust.accept_invitation(db_session, contact=row_owned)

        resp = await client.get("/circles", cookies=_cookies(viewer))
        assert resp.status_code == 200
        assert "Bob Backup" in resp.text
        assert "Cara Circle" in resp.text
        assert "Owned Contact" not in resp.text

    async def test_logged_out_redirects_to_login(self, client: AsyncClient):
        resp = await client.get("/circles", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/circles"


@pytest.mark.asyncio
class TestCircleAccept:
    async def test_accept_activates_and_sends_welcome_sms(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155597101", "+14155597102", code="ACCEPT01"
        )
        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ) as mock_welcome:
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/accept",
                cookies=_cookies(accepter),
                follow_redirects=False,
            )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/circles/ACCEPT01?accepted=1"
        mock_welcome.assert_awaited_once()

        member = await circle_invitations.get_member_for_accepter(
            db_session, inviter=inviter, accepter=accepter
        )
        await db_session.refresh(member)
        assert member.status == ContactStatus.ACTIVE

    async def test_accept_offers_referral_when_eligible(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155597103", "+14155597104", code="ACCEPT02"
        )
        inviter.share_code = "IVYSHARE"
        await db_session.commit()

        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ):
            resp = await _post_and_follow(
                client,
                f"/circles/{inviter.circle_invite_code}/accept",
                cookies=_cookies(accepter),
            )
        assert resp.status_code == 200
        assert "Get a free month!" in resp.text
        assert "Claim Free Month" in resp.text
        assert "IVYSHARE" in resp.text

    async def test_accept_does_not_offer_referral_when_accepter_already_has_one(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155597105", "+14155597106", code="ACCEPT03"
        )
        inviter.share_code = "IVYSHARE2"
        earlier_referrer = await create_test_user(
            db_session, phone_number="+14155597107", full_name="Earlier Referrer"
        )
        db_session.add(
            Referral(
                referrer_user_id=earlier_referrer.id,
                referral_code="EARLIER02",
                referee_user_id=accepter.id,
            )
        )
        await db_session.commit()

        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ):
            resp = await _post_and_follow(
                client,
                f"/circles/{inviter.circle_invite_code}/accept",
                cookies=_cookies(accepter),
            )
        assert resp.status_code == 200
        assert "You're in!" in resp.text
        assert "Claim Free Month" not in resp.text
        assert "IVYSHARE2" not in resp.text

    async def test_lowercase_code_is_accepted(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155597108", "+14155597109", code="ACCEPT04"
        )
        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ):
            resp = await _post_and_follow(
                client,
                f"/circles/{inviter.circle_invite_code.lower()}/accept",
                cookies=_cookies(accepter),
            )
        assert resp.status_code == 200
        assert "You're in!" in resp.text

    async def test_unknown_code_renders_invalid_state(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        someone = await create_test_user(
            db_session, phone_number="+14155597110", full_name="Someone"
        )
        resp = await client.post(
            "/circles/NOSUCHCODE/accept",
            cookies=_cookies(someone),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "This invite link isn't valid" in resp.text

    async def test_self_accept_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155597111",
            full_name="Ivy Inviter",
            circle_invite_code="ACCEPT05",
        )
        resp = await _post_and_follow(
            client, "/circles/ACCEPT05/accept", cookies=_cookies(inviter)
        )
        assert resp.status_code == 200
        assert "This is your own invite link" in resp.text

    async def test_logged_out_redirects_to_login_with_next(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155597112",
            full_name="Ivy Inviter",
            circle_invite_code="ACCEPT06",
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/accept", follow_redirects=False
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/circles/ACCEPT06"


@pytest.mark.asyncio
class TestCircleInviteLander:
    async def test_plain_revisit_of_active_membership_has_no_offer(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, member_user = await _active_member(
            db_session, "+14155597401", "+14155597402", code="LANDER01"
        )
        inviter.share_code = "LANDSHR1"
        await db_session.commit()

        resp = await client.get("/circles/LANDER01", cookies=_cookies(member_user))
        assert resp.status_code == 200
        assert "You're already in Ivy's Circle" in resp.text
        assert "You're in!" not in resp.text
        assert "Claim Free Month" not in resp.text
        assert "LANDSHR1" not in resp.text

    async def test_claim_swaps_only_the_offer_box_and_keeps_dnd_guidance(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155597403", "+14155597404", code="LANDER02"
        )
        inviter.share_code = "LANDSHR2"
        await db_session.commit()
        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ):
            resp = await _post_and_follow(
                client, "/circles/LANDER02/accept", cookies=_cookies(accepter)
            )
        assert resp.status_code == 200
        assert 'hx-target="closest .referral-offer"' in resp.text
        assert 'id="invite-result"' not in resp.text
        # The DND-bypass guidance sits OUTSIDE the swapped box.
        offer_end = resp.text.index("Claim Free Month")
        assert resp.text.index("Emergency Bypass") > offer_end
        # htmx (only needed for the claim button) is SRI-pinned.
        assert 'integrity="sha384-' in resp.text

    async def test_lander_is_web_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Circle members use mobile web only: no install-the-app / enter-
        the-code path, no "get the app" pitch, no Smart App Banner."""
        _inviter, member_user = await _active_member(
            db_session, "+14155597405", "+14155597406", code="LANDER03"
        )
        logged_out = await client.get("/circles/LANDER03")
        active = await client.get("/circles/LANDER03", cookies=_cookies(member_user))
        for resp in (logged_out, active):
            assert resp.status_code == 200
            assert "apple-itunes-app" not in resp.text
            assert "enter this invite code" not in resp.text
            assert "Get the app" not in resp.text
            assert "apps.apple.com" not in resp.text
            assert "play.google.com" not in resp.text
        assert "Accept on the web" in logged_out.text
        assert "Emergency Bypass" in active.text
        assert "/made-it-home.vcf" in active.text

    async def test_offer_is_never_made_to_the_inviter_themselves(
        self, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155597407",
            full_name="Ivy Inviter",
            circle_invite_code="LANDER04",
        )
        inviter.share_code = "LANDSHR4"
        await db_session.commit()
        assert (
            await referral_service.referral_offer_for(
                db_session, inviter=inviter, accepter=inviter
            )
            is None
        )


@pytest.mark.asyncio
class TestClaimFromInvite:
    async def test_logged_out_claim_returns_error_fragment_not_500(
        self, client: AsyncClient
    ):
        resp = await client.post(
            "/htmx/referrals/claim-from-invite", data={"referral_code": "ANYCODE1"}
        )
        assert resp.status_code == 200
        assert "session expired" in resp.text


@pytest.mark.asyncio
class TestCirclesPageFreshSession:
    async def test_circles_renders_invites_and_memberships_on_a_fresh_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        viewer = await create_test_user(
            db_session, phone_number="+14155597501", full_name="Dana Dash"
        )
        pending_inviter = await create_test_user(
            db_session,
            phone_number="+14155597502",
            full_name="Pat Pending",
            circle_invite_code="DASHP001",
        )
        await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=pending_inviter.id,
            obj_in=CircleOfTrustMemberCreate(contact_phone_number=viewer.phone_number),
        )
        active_inviter = await create_test_user(
            db_session,
            phone_number="+14155597503",
            full_name="Ari Active",
            circle_invite_code="DASHA001",
        )
        row = await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=active_inviter.id,
            obj_in=CircleOfTrustMemberCreate(contact_phone_number=viewer.phone_number),
        )
        await crud_circle_of_trust.accept_invitation(db_session, contact=row)
        # The viewer's OWN circle must not show under "Your Circles".
        owned_contact = await create_test_user(
            db_session, phone_number="+14155597504", full_name="Owen Owned"
        )
        owned = await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=viewer.id,
            obj_in=CircleOfTrustMemberCreate(
                contact_phone_number=owned_contact.phone_number
            ),
        )
        await crud_circle_of_trust.accept_invitation(db_session, contact=owned)
        cookies = _cookies(viewer)
        # Production requests get a fresh session: nothing preloaded in the
        # identity map, so a lazy `member.user` in the template would raise
        # MissingGreenlet (the 500 this pins).
        db_session.expunge_all()

        resp = await client.get("/circles", cookies=cookies)
        assert resp.status_code == 200
        assert "Pat Pending" in resp.text
        assert 'action="/circles/DASHP001/accept"' in resp.text
        assert 'action="/circles/DASHP001/decline"' in resp.text
        assert "Ari Active" in resp.text
        assert "Owen Owned" not in resp.text


@pytest.mark.asyncio
class TestCircleDecline:
    async def test_decline_soft_removes_the_pending_invite(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155597201", "+14155597202", code="DECLINE1"
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/decline",
            cookies=_cookies(accepter),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/circles"

        member = await circle_invitations.get_member_for_accepter(
            db_session, inviter=inviter, accepter=accepter
        )
        await db_session.refresh(member)
        assert member.status == ContactStatus.REMOVED

    async def test_impostor_cannot_decline_someone_elses_invite(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155597203", "+14155597204", code="DECLINE2"
        )
        impostor = await create_test_user(
            db_session, phone_number="+14155597205", full_name="Ian Impostor"
        )
        resp = await _post_and_follow(
            client,
            f"/circles/{inviter.circle_invite_code}/decline",
            cookies=_cookies(impostor),
        )
        # The impostor is a real logged-in user, so the redirect lands them
        # on their own (empty) /circles page — the "message" is just that
        # nothing about the real accepter's invite changed for them.
        assert resp.status_code == 200

        # The real accepter's PENDING row is untouched — the impostor has
        # no matching phone, so decline_circle_invite no-ops.
        member = await circle_invitations.get_member_for_accepter(
            db_session, inviter=inviter, accepter=accepter
        )
        await db_session.refresh(member)
        assert member.status == ContactStatus.PENDING

    async def test_declining_an_active_membership_is_a_noop(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, member_user = await _active_member(
            db_session, "+14155597207", "+14155597208", code="DECLINE4"
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/decline",
            cookies=_cookies(member_user),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        row = await circle_invitations.get_member_for_accepter(
            db_session, inviter=inviter, accepter=member_user
        )
        await db_session.refresh(row)
        assert row.status == ContactStatus.ACTIVE

    async def test_owner_cannot_decline_via_own_code(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, accepter = await _pending_invite(
            db_session, "+14155597209", "+14155597210", code="DECLINE5"
        )
        resp = await client.post(
            "/circles/DECLINE5/decline",
            cookies=_cookies(inviter),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        row = await circle_invitations.get_member_for_accepter(
            db_session, inviter=inviter, accepter=accepter
        )
        await db_session.refresh(row)
        assert row.status == ContactStatus.PENDING

    async def test_logged_out_redirects_to_login_with_next(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155597206",
            full_name="Ivy Inviter",
            circle_invite_code="DECLINE3",
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/decline", follow_redirects=False
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/circles/DECLINE3"


@pytest.mark.asyncio
class TestCircleLeave:
    async def test_leave_soft_removes_the_active_membership(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, member_user = await _active_member(
            db_session, "+14155597301", "+14155597302", code="LEAVE0001"
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/leave",
            cookies=_cookies(member_user),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/circles"

        row = await circle_invitations.get_member_for_accepter(
            db_session, inviter=inviter, accepter=member_user
        )
        # SOFT removal: the row still exists (unlike the old htmx handler's
        # hard `crud.remove`), just flipped to REMOVED.
        assert row is not None
        await db_session.refresh(row)
        assert row.status == ContactStatus.REMOVED

    async def test_leave_when_not_a_member_is_a_noop(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155597303",
            full_name="Ivy Inviter",
            circle_invite_code="LEAVE0002",
        )
        stranger = await create_test_user(
            db_session, phone_number="+14155597304", full_name="Stranger"
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/leave",
            cookies=_cookies(stranger),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/circles"

    async def test_owner_cannot_leave_via_own_code(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, member_user = await _active_member(
            db_session, "+14155597306", "+14155597307", code="LEAVE0004"
        )
        resp = await client.post(
            "/circles/LEAVE0004/leave",
            cookies=_cookies(inviter),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        row = await circle_invitations.get_member_for_accepter(
            db_session, inviter=inviter, accepter=member_user
        )
        await db_session.refresh(row)
        assert row.status == ContactStatus.ACTIVE

    async def test_logged_out_redirects_to_login_with_next(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155597305",
            full_name="Ivy Inviter",
            circle_invite_code="LEAVE0003",
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/leave", follow_redirects=False
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/circles/LEAVE0003"
