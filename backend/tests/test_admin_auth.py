import pytest
from httpx import AsyncClient

from app.models.user import User


@pytest.mark.asyncio
class TestAdminAuth:
    async def test_unauthenticated_redirects(self, client: AsyncClient):
        response = await client.get("/admin/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    async def test_non_admin_gets_403(
        self, client: AsyncClient, test_user: User
    ):
        from app.core.security import create_access_token

        token = create_access_token(str(test_user.id))
        response = await client.get(
            "/admin/", cookies={"access_token": token}
        )
        assert response.status_code == 403

    async def test_admin_gets_200(
        self, client: AsyncClient, admin_cookies: dict
    ):
        response = await client.get("/admin/", cookies=admin_cookies)
        assert response.status_code == 200
        assert "Dashboard" in response.text

    async def test_admin_dashboard_shows_metrics(
        self, client: AsyncClient, admin_cookies: dict
    ):
        response = await client.get("/admin/", cookies=admin_cookies)
        assert response.status_code == 200
        assert "Total Users" in response.text
        assert "Active Sessions" in response.text
        assert "Active Subscriptions" in response.text
