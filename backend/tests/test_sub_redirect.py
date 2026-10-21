"""Tests for the /sub short URL redirect (notification deep link)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
class TestSubRedirect:
    async def test_redirects_to_plans_paywall(self, client: AsyncClient):
        """The app now claims /sub itself and opens its own paywall (owner
        decision 2026-09-23) — the interim marketing-site bounce is gone.
        A 302, never a browser-cached 301: /sub rides in a frozen SMS body
        forever (sub_lapse_notifications.py), so its target must stay free
        to change without worrying about stale browser caches."""
        response = await client.get("/sub", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/plans"
