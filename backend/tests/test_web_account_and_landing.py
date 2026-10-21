"""GET/POST /account and the Circle-member login landing (owner decision
2026-09-23): the web dashboard + GET /profile are removed; /account is the
one hub for name + phone, and the default post-login target is /alerts.

CLAUDE.md says a name is always required for new users, but the web
sign-up (routes_htmx_auth.py verify_otp, routes_htmx_referral.py
referral_verify_otp) creates the user with full_name=None and nothing on
the web ever asked for it. `_require_name()` (routes_web.py) closes that
gap: every cookie-auth Circle-member page (GET /alerts, GET /circles,
GET /circles/{code}) redirects a nameless viewer to GET /account?next=<the
page they were headed to> first; the public GET /alerts/{id} page has no
current_user and is never gated.

Related: app/web/routes_web.py (_require_name, account_page,
account_update, alerts_page, circles_page, circle_invite_page,
login_page), app/web/routes_htmx_auth.py (verify_otp's redirect_url +
name gate), app/web/templates/account.html, app/web/utils.py
(safe_next_path — the one redirect-target validator, security.md).
"""

import json
import logging
import re
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.web.utils import safe_next_path
from tests.helpers import create_test_user


def _cookie(user: User) -> dict:
    return {"access_token": create_access_token(str(user.id))}


async def _make_session(db: AsyncSession, owner: User) -> Session:
    from datetime import UTC, datetime, timedelta

    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=SessionStatus.MISSED,
        tz_offset_minutes=-420,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _make_alert(db: AsyncSession, *, session: Session, recipient: User) -> Alert:
    from datetime import UTC, datetime

    alert = Alert(
        session_id=session.id,
        sent_to_user_id=recipient.id,
        alert_type=AlertType.MISSED_SESSION,
        status=AlertStatus.SENT,
        message="test alert body",
        sent_at=datetime.now(UTC),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@pytest.mark.asyncio
class TestLoginLanding:
    async def test_authenticated_login_defaults_to_alerts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598001", full_name="Landing User"
        )
        resp = await client.get("/login", cookies=_cookie(user), follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/alerts"

    async def test_authenticated_login_honors_safe_next(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598002", full_name="Landing User Next"
        )
        resp = await client.get(
            "/login?next=/circles", cookies=_cookie(user), follow_redirects=False
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/circles"

    async def test_verify_otp_redirects_named_user_to_alerts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(
            db_session, phone_number="+14155598003", full_name="Named Verifier"
        )
        with patch("app.services.otp.otp_service.verify_otp") as mock_verify:
            mock_verify.return_value = (True, "Verified")
            resp = await client.post(
                "/htmx/auth/verify-otp",
                data={"phone_number": "+14155598003", "otp_code": "123456"},
            )
        assert resp.status_code == 200
        assert '"/alerts"' in resp.text
        assert "/account?next=" not in resp.text

    async def test_verify_otp_sends_nameless_user_to_account(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(db_session, phone_number="+14155598004", full_name=None)
        with patch("app.services.otp.otp_service.verify_otp") as mock_verify:
            mock_verify.return_value = (True, "Verified")
            resp = await client.post(
                "/htmx/auth/verify-otp",
                data={"phone_number": "+14155598004", "otp_code": "123456"},
            )
        assert resp.status_code == 200
        assert "/account?next=/alerts" in resp.text


@pytest.mark.asyncio
class TestNameGateOnCircleMemberPages:
    async def test_alerts_redirects_nameless_user_to_account(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598101", full_name=None
        )
        resp = await client.get(
            "/alerts", cookies=_cookie(user), follow_redirects=False
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/account?next=/alerts"

    async def test_circles_redirects_nameless_user_to_account(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598102", full_name=None
        )
        resp = await client.get(
            "/circles", cookies=_cookie(user), follow_redirects=False
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/account?next=/circles"

    async def test_circle_invite_lander_redirects_nameless_logged_in_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter = await create_test_user(
            db_session,
            phone_number="+14155598103",
            full_name="Inviter",
            circle_invite_code="GATE0001",
        )
        viewer = await create_test_user(
            db_session, phone_number="+14155598104", full_name=None
        )
        resp = await client.get(
            f"/circles/{inviter.circle_invite_code}",
            cookies=_cookie(viewer),
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/account?next=/circles/GATE0001"

    async def test_named_user_is_not_gated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598105", full_name="Has A Name"
        )
        resp = await client.get("/alerts", cookies=_cookie(user))
        assert resp.status_code == 200

    async def test_public_alert_page_is_never_gated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155598106", full_name="Alert Owner"
        )
        member = await create_test_user(
            db_session, phone_number="+14155598107", full_name=None
        )
        session = await _make_session(db_session, owner)
        alert = await _make_alert(db_session, session=session, recipient=member)

        # A nameless viewer's cookie is irrelevant — the public page has no
        # current_user dependency at all.
        resp = await client.get(f"/alerts/{alert.id}", cookies=_cookie(member))
        assert resp.status_code == 200
        assert "/account?next=" not in resp.text


@pytest.mark.asyncio
class TestAccountPage:
    async def test_logged_out_account_redirects_to_login(self, client: AsyncClient):
        resp = await client.get("/account", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/account"

    async def test_post_account_saves_name_and_shows_saved(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598201", full_name=None
        )
        resp = await client.post(
            "/account",
            cookies=_cookie(user),
            data={"full_name": "  New Name  "},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/account?saved=1"

        follow = await client.get(resp.headers["location"], cookies=_cookie(user))
        assert follow.status_code == 200
        assert "Saved" in follow.text
        assert "New Name" in follow.text

    async def test_post_account_follows_safe_next(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598202", full_name=None
        )
        resp = await client.post(
            "/account",
            cookies=_cookie(user),
            data={"full_name": "Next Follower", "next": "/alerts"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/alerts"

    async def test_post_account_rejects_empty_name(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598203", full_name="Had A Name"
        )
        resp = await client.post(
            "/account",
            cookies=_cookie(user),
            data={"full_name": "   "},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        assert "Please enter your name" in resp.text
        # The form re-renders rather than redirecting — the previously
        # saved name is unchanged in the DB.
        await db_session.refresh(user)
        assert user.full_name == "Had A Name"

    async def test_post_account_rejects_double_slash_next(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598204", full_name=None
        )
        resp = await client.post(
            "/account",
            cookies=_cookie(user),
            data={"full_name": "Safe Name", "next": "//evil.example"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/account?saved=1"


@pytest.mark.asyncio
class TestRemovedDashboardAndProfileRoutes:
    async def test_dashboard_is_gone(self, client: AsyncClient):
        resp = await client.get("/dashboard", follow_redirects=False)
        assert resp.status_code == 404

    async def test_profile_is_gone(self, client: AsyncClient):
        resp = await client.get("/profile", follow_redirects=False)
        assert resp.status_code == 404

    async def test_htmx_profile_update_is_gone(self, client: AsyncClient):
        resp = await client.post(
            "/htmx/profile/update", data={"full_name": "X"}, follow_redirects=False
        )
        assert resp.status_code in (404, 405)


async def _verify_otp(
    client: AsyncClient, phone: str, next_url: str | None, *, ok: bool = True
):
    data = {"phone_number": phone, "otp_code": "123456"}
    if next_url is not None:
        data["next_url"] = next_url
    with patch("app.services.otp.otp_service.verify_otp") as mock_verify:
        mock_verify.return_value = (True, "Verified") if ok else (False, "Bad code")
        return await client.post("/htmx/auth/verify-otp", data=data)


def _js_redirect_target(html: str) -> str:
    match = re.search(r"window\.location\.replace\((\".*?\")\)", html)
    assert match, "verify-otp response has no JS redirect"
    return json.loads(match.group(1))


class TestSafeNextPath:
    """app/web/utils.safe_next_path — the one redirect-target validator."""

    @pytest.mark.parametrize(
        "url",
        [
            "/alerts",
            "/circles/ABC",
            "/circles/ABC?accepted=1",
            "/account?next=/circles/ABC",
            "/account?next=%2Fcircles%2FA%3Fx%3D1",
            "/%5cevil.com",  # stays percent-encoded — a same-origin path
        ],
    )
    def test_accepts_same_origin_paths(self, url: str):
        assert safe_next_path(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            None,
            "",
            "None",
            "alerts",
            "https://evil.example",
            "javascript:alert(1)",
            "//evil.example",
            "/\\evil.example",
            "/\\/evil.example",
            "/\t/evil.example",
            "/\n/evil.example",
            "/a b",
            "/\x7f",
            '/x"}',
            "/x'",
            "/<script>",
            "/a>b",
        ],
    )
    def test_rejects_unsafe_targets(self, url: str | None):
        assert safe_next_path(url) is None
        assert safe_next_path(url, default="/fallback") == "/fallback"


@pytest.mark.asyncio
class TestNestedNextRoundTrip:
    async def test_logged_out_account_next_survives_login_otp_and_save(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """/account?next=/circles/ABC (logged out) → /login → OTP (nameless)
        → /account?next=/circles/ABC → save → /circles/ABC. One save — the
        OTP step must not wrap an /account target in another /account."""
        resp = await client.get("/account?next=/circles/ABC", follow_redirects=False)
        assert resp.status_code == 302
        login_url = resp.headers["location"]
        assert login_url == "/login?next=/account%3Fnext%3D/circles/ABC"

        login = await client.get(login_url)
        assert login.status_code == 200
        hidden = re.search(r'name="next_url" value="([^"]*)"', login.text)
        assert hidden and hidden.group(1) == "/account?next=/circles/ABC"

        user = await create_test_user(
            db_session, phone_number="+14155598301", full_name=None
        )
        verified = await _verify_otp(client, "+14155598301", hidden.group(1))
        target = _js_redirect_target(verified.text)
        assert target == "/account?next=/circles/ABC"

        page = await client.get(target, cookies=_cookie(user))
        assert page.status_code == 200
        form_next = re.search(r'name="next" value="([^"]*)"', page.text)
        assert form_next and form_next.group(1) == "/circles/ABC"

        saved = await client.post(
            "/account",
            cookies=_cookie(user),
            data={"full_name": "Round Trip", "next": form_next.group(1)},
            follow_redirects=False,
        )
        assert saved.status_code == 303
        assert saved.headers["location"] == "/circles/ABC"

    async def test_logged_out_account_keeps_query_in_next(self, client: AsyncClient):
        resp = await client.get(
            "/account?next=/circles/A%3Fx%3D1%26y%3D2", follow_redirects=False
        )
        assert resp.status_code == 302
        # Double-encoded: /login's next decodes to
        # /account?next=/circles/A%3Fx%3D1%26y%3D2, which decodes again to
        # /circles/A?x=1&y=2 on /account.
        assert resp.headers["location"] == (
            "/login?next=/account%3Fnext%3D/circles/A%253Fx%253D1%2526y%253D2"
        )

    async def test_logged_out_post_account_keeps_next(self, client: AsyncClient):
        resp = await client.post(
            "/account",
            data={"full_name": "Nobody", "next": "/circles/ABC"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/account%3Fnext%3D/circles/ABC"

    async def test_logged_out_post_account_drops_unsafe_next(self, client: AsyncClient):
        resp = await client.post(
            "/account",
            data={"full_name": "Nobody", "next": "//evil.example"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login?next=/account"


@pytest.mark.asyncio
class TestLandingEdgeCases:
    async def test_login_for_nameless_logged_in_user_reaches_account_without_loop(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598401", full_name=None
        )
        first = await client.get(
            "/login", cookies=_cookie(user), follow_redirects=False
        )
        assert first.status_code == 302
        assert first.headers["location"] == "/alerts"
        second = await client.get(
            first.headers["location"], cookies=_cookie(user), follow_redirects=False
        )
        assert second.status_code == 302
        assert second.headers["location"] == "/account?next=/alerts"
        third = await client.get(
            second.headers["location"], cookies=_cookie(user), follow_redirects=False
        )
        assert third.status_code == 200  # /account itself is never gated

    async def test_account_renders_safe_next_and_drops_unsafe(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598402", full_name="Has Name"
        )
        ok = await client.get("/account?next=/circles/ABC", cookies=_cookie(user))
        assert ok.status_code == 200
        assert 'name="next" value="/circles/ABC"' in ok.text

        bad = await client.get("/account?next=//evil.example", cookies=_cookie(user))
        assert bad.status_code == 200
        assert 'name="next"' not in bad.text
        assert "evil.example" not in bad.text

    async def test_verify_otp_keeps_query_in_next(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(
            db_session, phone_number="+14155598403", full_name="Query Keeper"
        )
        resp = await _verify_otp(client, "+14155598403", "/circles/X?accepted=1")
        assert _js_redirect_target(resp.text) == "/circles/X?accepted=1"

    async def test_verify_otp_keeps_query_through_name_gate(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await create_test_user(db_session, phone_number="+14155598404", full_name=None)
        resp = await _verify_otp(client, "+14155598404", "/circles/X?accepted=1")
        assert (
            _js_redirect_target(resp.text) == "/account?next=/circles/X%3Faccepted%3D1"
        )


@pytest.mark.asyncio
class TestUnsafeNextRejected:
    @pytest.mark.parametrize("bad", ["/\\evil.example", '/x"}'])
    async def test_verify_otp_falls_back_to_alerts(
        self, client: AsyncClient, db_session: AsyncSession, bad: str
    ):
        await create_test_user(
            db_session, phone_number="+14155598501", full_name="Named Target"
        )
        resp = await _verify_otp(client, "+14155598501", bad)
        assert _js_redirect_target(resp.text) == "/alerts"

    async def test_verify_otp_leaves_percent_encoded_backslash_encoded(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # A literal "%5c" in the form value is a same-origin path; it must
        # reach the browser still encoded (never as a real backslash).
        await create_test_user(
            db_session, phone_number="+14155598502", full_name="Named Target"
        )
        resp = await _verify_otp(client, "+14155598502", "/%5cevil.example")
        target = _js_redirect_target(resp.text)
        assert target == "/%5cevil.example"
        assert "\\" not in target

    async def test_login_rejects_decoded_percent_backslash(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # In a query string "%5c" decodes to "\\" before validation.
        user = await create_test_user(
            db_session, phone_number="+14155598503", full_name="Named Target"
        )
        resp = await client.get(
            "/login?next=/%5cevil.example",
            cookies=_cookie(user),
            follow_redirects=False,
        )
        assert resp.headers["location"] == "/alerts"

    @pytest.mark.parametrize("bad", ["/\\evil.example", "/%5cevil.example", '/x"}'])
    async def test_post_account_never_redirects_off_site(
        self, client: AsyncClient, db_session: AsyncSession, bad: str
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598504", full_name=None
        )
        resp = await client.post(
            "/account",
            cookies=_cookie(user),
            data={"full_name": "Safe Name", "next": bad},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        location = resp.headers["location"]
        assert location.startswith("/") and not location.startswith("//")
        assert "\\" not in location
        if bad != "/%5cevil.example":
            assert location == "/account?saved=1"

    async def test_quote_in_next_cannot_inject_into_hx_vals(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """fragments/auth_form.html puts next_url inside hx-vals JSON; the
        HTML parser undoes Jinja's &#34; before htmx parses it, so a `"`
        in next could add JSON keys. safe_next_path drops such a value."""
        resp = await _verify_otp(
            client, "+14155598505", '/x", "phone_number": "+1999"}', ok=False
        )
        assert resp.status_code == 200
        assert "hx-vals" in resp.text
        assert "+1999" not in resp.text
        assert "/x&#34;" not in resp.text


@pytest.mark.asyncio
class TestAccountNameValidation:
    async def test_over_long_name_is_friendly_and_not_reported(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598601", full_name="Keep Me"
        )
        with caplog.at_level(logging.ERROR):
            resp = await client.post(
                "/account",
                cookies=_cookie(user),
                data={"full_name": "x" * 101},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        assert "Please enter your name (up to 100 characters)" in resp.text
        # User-input rejection is benign — nothing at ERROR+ reaches Bugsnag.
        assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
        await db_session.refresh(user)
        assert user.full_name == "Keep Me"

    async def test_account_input_has_maxlength(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598602", full_name="Max Len"
        )
        resp = await client.get("/account", cookies=_cookie(user))
        assert 'maxlength="100"' in resp.text

    async def test_db_failure_is_reported_and_rerenders(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ):
        user = await create_test_user(
            db_session, phone_number="+14155598603", full_name="Db Fail"
        )
        with (
            patch(
                "app.web.routes_web.crud_user.update",
                side_effect=RuntimeError("db down"),
            ),
            caplog.at_level(logging.ERROR),
        ):
            resp = await client.post(
                "/account",
                cookies=_cookie(user),
                data={"full_name": "New Name"},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        assert "Failed to update profile" in resp.text
        assert any(
            r.levelno >= logging.ERROR and "Error updating account name" in r.message
            for r in caplog.records
        )
