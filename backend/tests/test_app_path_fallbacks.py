"""Browser fallback behavior for the app-claimed paths: /plans and
/subscription (the app's Stripe checkout-return URLs) and /sub (the
frozen lapse-SMS link, which lands on /plans). An installed app MAY
intercept all three via universal link before the request reaches the
server (a tapped link usually is; a Stripe return's script-driven redirect
often isn't); these tests cover what a browser sees when it isn't, keyed
off the User-Agent (app/web/utils.py:store_redirect_url).

Related: app/web/routes_web.py (plans_web_fallback,
subscription_web_fallback, the registry-driven /sub redirect),
app/web/short_links.py (CLAIMED_APP_PATHS), tests/test_store_links.py
(the pinned store URLs).
"""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.web.utils import store_redirect_url

# The pinned store URLs (the real App Store Connect id / Play package) —
# asserting against these, not app.web.utils' own constants, is what keeps
# the fallback honest if someone edits the constants.
from tests.test_store_links import ANDROID_URL as ANDROID_PLAY_STORE_URL
from tests.test_store_links import IOS_URL as IOS_APP_STORE_URL

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
IPAD_UA = (
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Mobile Safari/537.36"
)
DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class TestStoreRedirectUrlHelper:
    """Cases the route tests below don't cover (iPhone / Android /
    desktop are exercised through the routes)."""

    def test_ipad_goes_to_ios_store(self):
        assert (
            store_redirect_url(IPAD_UA, marketing_origin="https://m.example.com")
            == IOS_APP_STORE_URL
        )

    def test_missing_user_agent_goes_to_marketing(self):
        assert (
            store_redirect_url(None, marketing_origin="https://m.example.com")
            == "https://m.example.com"
        )


@pytest.mark.asyncio
class TestPlansWebFallback:
    async def test_iphone(self, client: AsyncClient):
        response = await client.get(
            "/plans", headers={"user-agent": IPHONE_UA}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == IOS_APP_STORE_URL

    async def test_android(self, client: AsyncClient):
        response = await client.get(
            "/plans", headers={"user-agent": ANDROID_UA}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == ANDROID_PLAY_STORE_URL

    async def test_desktop_goes_to_marketing_origin(self, client: AsyncClient):
        response = await client.get(
            "/plans", headers={"user-agent": DESKTOP_UA}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == settings.MARKETING_ORIGIN

    async def test_stripe_success_return_with_query(self, client: AsyncClient):
        """The Stripe success_url carries a query string; a browser that
        reaches it (the OS didn't hand it to the app) still gets the store
        fallback, never a 404/422."""
        response = await client.get(
            "/plans?checkout=success&session_id=cs_test_123",
            headers={"user-agent": ANDROID_UA},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.headers["location"] == ANDROID_PLAY_STORE_URL


@pytest.mark.asyncio
class TestSubscriptionWebFallback:
    async def test_iphone(self, client: AsyncClient):
        response = await client.get(
            "/subscription", headers={"user-agent": IPHONE_UA}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == IOS_APP_STORE_URL

    async def test_android(self, client: AsyncClient):
        response = await client.get(
            "/subscription", headers={"user-agent": ANDROID_UA}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == ANDROID_PLAY_STORE_URL

    async def test_desktop_goes_to_marketing_origin(self, client: AsyncClient):
        response = await client.get(
            "/subscription", headers={"user-agent": DESKTOP_UA}, follow_redirects=False
        )
        assert response.status_code == 302
        assert response.headers["location"] == settings.MARKETING_ORIGIN


@pytest.mark.asyncio
class TestSubOnBrowserChainsToStore:
    """`/sub` (the frozen lapse-SMS link) -> /plans -> store, exactly like
    any other browser hitting an app-claimed path with the app not
    installed."""

    async def test_sub_then_plans_then_store_on_iphone(self, client: AsyncClient):
        sub_response = await client.get("/sub", follow_redirects=False)
        assert sub_response.status_code == 302
        assert sub_response.headers["location"] == "/plans"

        plans_response = await client.get(
            sub_response.headers["location"],
            headers={"user-agent": IPHONE_UA},
            follow_redirects=False,
        )
        assert plans_response.status_code == 302
        assert plans_response.headers["location"] == IOS_APP_STORE_URL
