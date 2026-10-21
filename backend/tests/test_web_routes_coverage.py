"""Coverage tests for web routes — HTMX endpoints and web views."""

import secrets

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.user import User
from tests.helpers import create_test_user


def _cookie(user: User) -> dict:
    return {"access_token": create_access_token(str(user.id))}


async def _make_user(
    db: AsyncSession, phone: str = "+14155590010", name: str = "Web User"
) -> User:
    user = await create_test_user(db, phone_number=phone, full_name=name)
    if not user.share_code:
        user.share_code = secrets.token_hex(4).upper()
        await db.commit()
        await db.refresh(user)
    return user


@pytest.mark.asyncio
class TestWebPages:
    async def test_landing_page(self, client: AsyncClient):
        """Marketing lives only on the marketing-site repo (owner decision
        2026-09-23) — GET / is a permanent redirect there, not a page."""
        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 301

    async def test_login_page(self, client: AsyncClient):
        response = await client.get("/login")
        assert response.status_code == 200

    async def test_account_authenticated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14155590100")
        response = await client.get("/account", cookies=_cookie(user))
        assert response.status_code in (200, 302, 303)

    async def test_account_unauthenticated(self, client: AsyncClient):
        response = await client.get("/account", follow_redirects=False)
        assert response.status_code in (302, 303, 401)

    async def test_alerts_page(self, client: AsyncClient, db_session: AsyncSession):
        user = await _make_user(db_session, "+14155590300")
        response = await client.get("/alerts", cookies=_cookie(user))
        assert response.status_code == 200

    async def test_circles_page(self, client: AsyncClient, db_session: AsyncSession):
        user = await _make_user(db_session, "+14155590310")
        response = await client.get("/circles", cookies=_cookie(user))
        assert response.status_code in (200, 302, 303)

    async def test_sponsorships_new_page(self, client: AsyncClient):
        response = await client.get("/sponsorships/new")
        assert response.status_code in (200, 302, 303)

    async def test_sponsorship_page_with_share_code(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14155590320")
        response = await client.get(f"/sponsorships/{user.share_code}")
        assert response.status_code in (200, 302, 303)

    async def test_sponsorship_short_link(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14155590321")
        response = await client.get(f"/s/{user.share_code}", follow_redirects=False)
        assert response.status_code in (301, 302, 307, 308)

    async def test_referral_page(self, client: AsyncClient, db_session: AsyncSession):
        user = await _make_user(db_session, "+14155590330")
        response = await client.get(f"/referrals/{user.share_code}")
        assert response.status_code in (200, 302, 303)

    async def test_logout(self, client: AsyncClient):
        response = await client.get("/logout", follow_redirects=False)
        assert response.status_code in (302, 303, 307)
        assert response.headers["location"] == "/login"


@pytest.mark.asyncio
class TestHTMXSponsorshipRoutes:
    async def test_sponsorship_request_otp(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14155590500")
        response = await client.post(
            f"/htmx/sponsorships/{user.share_code}/request-otp",
            data={
                "gifter_phone": "+14155590501",
                "recipient_phone": "+14155590502",
            },
        )
        assert response.status_code in (200, 302, 303, 422)


@pytest.mark.asyncio
class TestHTMXReferralRoutes:
    async def test_referral_request_otp(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14155590600")
        response = await client.post(
            "/htmx/referrals/request-otp",
            data={
                "phone_number": "+14155590601",
                "referral_code": user.share_code,
            },
        )
        assert response.status_code in (200, 302, 303, 422)
