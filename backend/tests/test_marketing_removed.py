"""Marketing lives only on the marketing-site repo (owner decision
2026-09-23) — the app backend serves no marketing or pricing page.

Pins: GET / is a permanent redirect to MARKETING_ORIGIN (never a rendered
page); GET /sub is a 302 to /plans (the app's own paywall, owner decision
2026-09-23 — kept temporary/302 rather than 301 because /sub rides in a
frozen SMS body forever); GET /pricing is gone entirely; GET /logout 303s to
/login (there is no in-app "/" to return to) and expires the auth cookie
with the attributes `set_auth_cookie` set it with; login.html's header logo
links to the marketing origin and carries no link to the removed /pricing
page; and the lapsed-subscription SMS text (frozen —
app/services/sub_lapse_notifications.py) is untouched by this change.

Related: app/web/routes_web.py, app/web/utils.py (set/clear_auth_cookie),
app/core/config.py (MARKETING_ORIGIN), app/services/sub_lapse_notifications.py.
"""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.security import create_access_token
from app.services.sub_lapse_notifications import (
    _GROUP_SMS,
    _SPONSOR_SMS,
    SUB_SHORT_URL,
    Moment,
)


@pytest.mark.asyncio
class TestMarketingRemoved:
    async def test_root_redirects_to_marketing_origin(self, client: AsyncClient):
        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == settings.MARKETING_ORIGIN

    async def test_pricing_page_gone(self, client: AsyncClient):
        response = await client.get("/pricing")
        assert response.status_code == 404

    async def test_sub_redirects_to_plans_paywall(self, client: AsyncClient):
        """302 (not 301) so browsers never cache it past a future change —
        /sub rides in a frozen SMS body forever."""
        response = await client.get("/sub", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/plans"

    async def test_logout_redirects_to_login_and_clears_cookie(
        self, client: AsyncClient
    ):
        token = create_access_token("00000000-0000-0000-0000-000000000000")
        response = await client.get(
            "/logout", cookies={"access_token": token}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
        cookie_header = response.headers["set-cookie"]
        attrs = [part.strip().lower() for part in cookie_header.split(";")]
        # Expired, empty value, same path as set_auth_cookie (default "/")
        # so the browser matches and drops the cookie it holds.
        assert attrs[0] == 'access_token=""'
        assert "max-age=0" in attrs
        assert "path=/" in attrs
        assert "secure" in attrs
        assert "httponly" in attrs
        assert "samesite=lax" in attrs

    async def test_login_page_has_no_pricing_link(self, client: AsyncClient):
        response = await client.get("/login")
        assert response.status_code == 200
        assert "/pricing" not in response.text

    async def test_login_logo_links_to_marketing_origin(self, client: AsyncClient):
        """`marketing_origin` is a Jinja global — an env missing it renders
        an empty href silently, so pin the rendered value."""
        response = await client.get("/login")
        assert response.status_code == 200
        assert f'href="{settings.MARKETING_ORIGIN}"' in response.text

    async def test_lapse_sms_short_url_unchanged(self):
        """The SMS text is frozen — only the server-side behavior of the
        /sub route it embeds changes in this commit."""
        assert SUB_SHORT_URL == "https://madeitho.me/sub"
        for body in _GROUP_SMS.values():
            assert SUB_SHORT_URL in body
        for body in _SPONSOR_SMS.values():
            assert SUB_SHORT_URL in body
        # Every moment has copy in both fan-outs — the builder wasn't
        # touched, but pin the shape so a future edit can't quietly drop one.
        assert set(_GROUP_SMS) == set(Moment)
        assert set(_SPONSOR_SMS) == set(Moment)
