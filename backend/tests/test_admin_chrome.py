"""Admin chrome: header shows the Made It Home logo + wordmark + an "Admin"
badge, and there is no marketing footer.

Related: app/web/templates/admin/base_admin.html, app/web/templates/base_web.html.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_admin_header_has_wordmark_and_badge(
    client: AsyncClient, admin_cookies: dict
):
    r = await client.get("/admin/users", cookies=admin_cookies)
    assert r.status_code == 200
    body = r.text
    assert "Made It Home" in body  # wordmark
    assert 'class="admin-badge"' in body  # the Admin badge


@pytest.mark.asyncio
async def test_admin_has_no_footer(client: AsyncClient, admin_cookies: dict):
    r = await client.get("/admin/users", cookies=admin_cookies)
    assert r.status_code == 200
    # The marketing footer (store badges) must not appear on admin pages.
    assert "Google Play" not in r.text
    assert "App Store" not in r.text
