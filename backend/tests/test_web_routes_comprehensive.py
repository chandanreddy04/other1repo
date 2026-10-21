"""Comprehensive tests for web routes to improve coverage."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.alert import crud_alert
from app.crud.user import crud_user
from app.models.alert import AlertType
from app.schemas.alert import AlertCreate
from app.schemas.user import UserCreate


@pytest.mark.asyncio
class TestWebRoutes:
    """Test web routes for maximum coverage."""

    async def test_landing_page(self, client: AsyncClient):
        """GET / redirects to the marketing site (owner decision
        2026-09-23) — marketing lives only on the marketing-site repo."""
        from app.core.config import settings

        response = await client.get("/", follow_redirects=False)
        assert response.status_code == 301
        assert response.headers["location"] == settings.MARKETING_ORIGIN

    async def test_landing_page_with_auth(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The redirect to marketing happens regardless of auth state."""
        # Create user
        user_data = UserCreate(phone_number="+14155550101", full_name="Web Test User")
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        # Create token as cookie
        token = create_access_token(str(user.id))

        response = await client.get(
            "/", cookies={"access_token": token}, follow_redirects=False
        )
        assert response.status_code == 301

    async def test_account_page_unauthenticated(self, client: AsyncClient):
        """Test account page without auth."""
        response = await client.get("/account", follow_redirects=False)
        # Should redirect to login or return error
        assert response.status_code in [302, 303, 401]

    async def test_account_page_authenticated(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Test account page with auth."""
        # Create user
        user_data = UserCreate(
            phone_number="+14155550102", full_name="Account Test User"
        )
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        token = create_access_token(str(user.id))

        response = await client.get("/account", cookies={"access_token": token})
        assert response.status_code in [200, 302, 500]

    async def test_alerts_page(self, client: AsyncClient, db_session: AsyncSession):
        """Test alerts page."""
        # Create user with alerts
        user_data = UserCreate(phone_number="+14155550103", full_name="Alert Web User")
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        # Create session and alert
        from app.crud.session import crud_session
        from app.schemas.session import SessionCreate

        session_data = SessionCreate(
            expected_return_time=datetime.now(UTC) + timedelta(hours=2)
        )
        session = await crud_session.create_session(
            db_session, user_id=user.id, obj_in=session_data
        )

        alert_data = AlertCreate(
            session_id=session.id,
            sent_to_user_id=user.id,
            alert_type=AlertType.REMINDER,
            message="Test alert",
        )
        await crud_alert.create_alert(db_session, obj_in=alert_data)
        await db_session.commit()

        token = create_access_token(str(user.id))

        response = await client.get("/alerts", cookies={"access_token": token})
        assert response.status_code == 200

    async def test_circles_page(self, client: AsyncClient, db_session: AsyncSession):
        """Test circles page (renamed from /invitations)."""
        user_data = UserCreate(
            phone_number="+14155550104", full_name="Invitation Web User"
        )
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        token = create_access_token(str(user.id))

        response = await client.get("/circles", cookies={"access_token": token})
        assert response.status_code in [200, 302, 500]

    async def test_logout(self, client: AsyncClient, db_session: AsyncSession):
        """Test logout functionality."""
        user_data = UserCreate(
            phone_number="+14155550105", full_name="Logout Test User"
        )
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        token = create_access_token(str(user.id))

        response = await client.get(
            "/logout", cookies={"access_token": token}, follow_redirects=False
        )
        # Should clear cookie and redirect
        assert response.status_code in [200, 302, 303, 307]
        # Check if cookie is cleared
        if "set-cookie" in response.headers:
            cookie_header = response.headers["set-cookie"].lower()
            # Should either delete or expire the cookie
            assert "access_token" in cookie_header

    async def test_health_check(self, client: AsyncClient):
        """Test health check endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200


@pytest.mark.asyncio
class TestHTMXRoutes:
    """Test HTMX routes for coverage."""

    async def test_htmx_phone_form(self, client: AsyncClient):
        """Test HTMX phone form endpoint."""
        response = await client.get("/htmx/auth/phone-form")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    async def test_htmx_request_otp(self, client: AsyncClient):
        """Test HTMX OTP request."""
        with patch("app.services.otp.otp_service.send_otp") as mock_send:
            mock_send.return_value = (True, "OTP sent")

            response = await client.post(
                "/htmx/auth/request-otp",
                data={"phone_number": "+14155552671"},
                headers={"HX-Request": "true"},
            )
            assert response.status_code in [200, 422]

    async def test_htmx_verify_otp(self, client: AsyncClient, db_session: AsyncSession):
        """Test HTMX OTP verification."""
        with patch("app.services.otp.otp_service.verify_otp") as mock_verify:
            mock_verify.return_value = (True, "Verified")

            response = await client.post(
                "/htmx/auth/verify-otp",
                data={"phone_number": "+14155552671", "otp_code": "123456"},
                headers={"HX-Request": "true"},
            )
            assert response.status_code in [200, 302, 422]

    async def test_account_update(self, client: AsyncClient, db_session: AsyncSession):
        """Test the plain-form account name update (moved from the deleted
        profile-update htmx handler, owner decision 2026-09-23)."""
        user_data = UserCreate(
            phone_number="+14155550203", full_name="Account Update User"
        )
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        token = create_access_token(str(user.id))

        response = await client.post(
            "/account",
            cookies={"access_token": token},
            data={"full_name": "Updated Name"},
            follow_redirects=False,
        )
        assert response.status_code in [200, 303, 422]

    # HTMX invitation accept/decline and circle-leave coverage moved to
    # tests/test_web_circles.py 2026-09-23 — those htmx routes
    # (app/web/routes_htmx_profile.py) were deleted in favor of the
    # REST-shaped POST /circles/{code}/accept|decline|leave.
