"""Pins the 2026-09-23 REST-path renames for the remaining user-facing web
pages (owner decision — REST-shaped URLs; vocabulary: Session / mark safe /
Account / Group Plan). No aliases were shipped: the old paths are gone
(404/405), the new paths respond.

Related: app/web/routes_web.py (/referrals/{code}, /groups/{invite_code}),
app/web/routes_web_delete.py (/account/delete...), app/web/routes_admin.py
(/admin/sessions/{id}/mark-safe).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.session import Session, SessionStatus
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestOldPathsAreGone:
    async def test_old_referral_path_404s(self, client: AsyncClient):
        resp = await client.get("/referral/ANYCODE1")
        assert resp.status_code == 404

    async def test_old_group_path_404s(self, client: AsyncClient):
        resp = await client.get("/group/ANYCODE1")
        assert resp.status_code == 404

    async def test_old_delete_account_get_404s(self, client: AsyncClient):
        resp = await client.get("/delete-account")
        assert resp.status_code == 404

    async def test_old_delete_account_start_404s(self, client: AsyncClient):
        resp = await client.post(
            "/delete-account/start", data={"phone_number": "+14155551234"}
        )
        assert resp.status_code == 404

    async def test_old_delete_account_verify_404s(self, client: AsyncClient):
        resp = await client.post(
            "/delete-account/verify",
            data={"phone_number": "+14155551234", "otp_code": "000000"},
        )
        assert resp.status_code == 404

    async def test_old_delete_account_confirm_404s(self, client: AsyncClient):
        resp = await client.post(
            "/delete-account/confirm", data={"confirm_phrase": "delete"}
        )
        assert resp.status_code == 404

    async def test_old_admin_checkin_on_behalf_get_404s(
        self, client: AsyncClient, admin_cookies: dict
    ):
        resp = await client.get(
            f"/admin/sessions/{uuid.uuid4()}/checkin-on-behalf",
            cookies=admin_cookies,
        )
        assert resp.status_code == 404

    async def test_old_admin_checkin_on_behalf_post_404s(
        self, client: AsyncClient, admin_cookies: dict
    ):
        resp = await client.post(
            f"/admin/sessions/{uuid.uuid4()}/checkin-on-behalf",
            cookies=admin_cookies,
        )
        assert resp.status_code == 404

    async def test_old_htmx_referral_paths_404(self, client: AsyncClient):
        resp = await client.post(
            "/htmx/referral/request-otp",
            data={"phone_number": "+14155551234", "referral_code": "ANYCODE1"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestNewPathsRespond:
    async def test_referrals_lander_responds(self, client: AsyncClient):
        resp = await client.get("/referrals/ANYCODE1")
        assert resp.status_code == 200

    async def test_groups_lander_responds(self, client: AsyncClient):
        resp = await client.get("/groups/ANYCODE1")
        assert resp.status_code == 200

    async def test_account_delete_landing_responds(self, client: AsyncClient):
        resp = await client.get("/account/delete")
        assert resp.status_code == 200

    async def test_account_delete_renders_deletion_phone_form(
        self, client: AsyncClient
    ):
        """/account/delete is its own page, not swallowed by GET /account."""
        resp = await client.get("/account/delete", follow_redirects=False)
        assert resp.status_code == 200
        assert "Delete your account" in resp.text
        assert 'name="phone_number"' in resp.text

    async def test_account_is_still_the_account_page(self, client: AsyncClient):
        """GET /account keeps its own handler (logged out → /login), not the
        deletion flow — the two routes don't shadow each other."""
        resp = await client.get("/account", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/account"

    async def test_account_delete_is_not_name_gated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The deletion flow needs no sign-in by design; a logged-in nameless
        viewer still gets the phone form, never the /account name gate."""
        user = await create_test_user(
            db_session, phone_number="+14155559880", full_name=None
        )
        resp = await client.get(
            "/account/delete",
            cookies={"access_token": create_access_token(str(user.id))},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "Delete your account" in resp.text
        assert 'name="phone_number"' in resp.text

    async def test_account_delete_codes_responds(self, client: AsyncClient):
        resp = await client.post(
            "/account/delete/codes", data={"phone_number": "+14155559876"}
        )
        assert resp.status_code == 200

    async def test_account_delete_verifications_responds(self, client: AsyncClient):
        resp = await client.post(
            "/account/delete/verifications",
            data={"phone_number": "+14155559876", "otp_code": "000000"},
        )
        assert resp.status_code == 200

    async def test_account_delete_confirmations_responds(self, client: AsyncClient):
        resp = await client.post(
            "/account/delete/confirmations", data={"confirm_phrase": "delete"}
        )
        assert resp.status_code == 200

    async def test_admin_mark_safe_get_responds(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        from datetime import UTC, datetime, timedelta

        owner = await create_test_user(
            db_session, phone_number="+14155559877", full_name="Path Owner"
        )
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC) - timedelta(hours=1),
            status=SessionStatus.MISSED.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        resp = await client.get(
            f"/admin/sessions/{session.id}/mark-safe", cookies=admin_cookies
        )
        assert resp.status_code == 200

    async def test_htmx_referrals_request_otp_responds(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155559878", full_name="Ref Owner"
        )
        user.share_code = "REFPATH1"
        await db_session.commit()

        resp = await client.post(
            "/htmx/referrals/request-otp",
            data={"phone_number": "+14155559879", "referral_code": "REFPATH1"},
        )
        assert resp.status_code == 200
