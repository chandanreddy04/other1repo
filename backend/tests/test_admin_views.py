from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.web.admin_registry import ALL_VIEWS
from app.web.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, generate_csrf_token
from tests.helpers import create_test_user


def _csrf_cookies(admin_cookies: dict) -> dict:
    """Return admin cookies merged with a CSRF cookie."""
    token = generate_csrf_token()
    return {**admin_cookies, CSRF_COOKIE_NAME: token}, token


def _csrf_data(token: str, **extra: str) -> dict:
    """Return form data with the CSRF token included."""
    return {CSRF_FORM_FIELD: token, **extra}


@pytest.mark.asyncio
class TestAdminListViews:
    """Test that every entity list view returns 200 for admin."""

    @pytest.mark.parametrize(
        "path",
        [v.name_plural for v in ALL_VIEWS],
        ids=[v.name_plural for v in ALL_VIEWS],
    )
    async def test_list_view_returns_200(
        self, client: AsyncClient, admin_cookies: dict, path: str
    ):
        response = await client.get(f"/admin/{path}", cookies=admin_cookies)
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "path",
        [v.name_plural for v in ALL_VIEWS],
        ids=[v.name_plural for v in ALL_VIEWS],
    )
    async def test_list_view_requires_admin(
        self, client: AsyncClient, test_user: User, path: str
    ):
        from app.core.security import create_access_token

        token = create_access_token(str(test_user.id))
        response = await client.get(
            f"/admin/{path}", cookies={"access_token": token}
        )
        assert response.status_code == 403


@pytest.mark.asyncio
class TestAdminUserViews:
    """Test CRUD operations on the Users entity."""

    async def test_users_list_shows_users(
        self, client: AsyncClient, admin_cookies: dict, test_user: User
    ):
        response = await client.get("/admin/users", cookies=admin_cookies)
        assert response.status_code == 200
        assert test_user.full_name in response.text

    async def test_users_search(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession
    ):
        await create_test_user(db_session, "+14155559999", full_name="Unique Searchable Name")
        response = await client.get(
            "/admin/users/htmx/table?search=Unique+Searchable",
            cookies=admin_cookies,
        )
        assert response.status_code == 200
        assert "Unique Searchable Name" in response.text

    async def test_users_detail(
        self, client: AsyncClient, admin_cookies: dict, test_user: User
    ):
        response = await client.get(
            f"/admin/users/{test_user.id}", cookies=admin_cookies
        )
        assert response.status_code == 200
        assert test_user.full_name in response.text

    async def test_users_detail_not_found(
        self, client: AsyncClient, admin_cookies: dict
    ):
        import uuid

        response = await client.get(
            f"/admin/users/{uuid.uuid4()}", cookies=admin_cookies
        )
        assert response.status_code == 404

    async def test_users_edit_form(
        self, client: AsyncClient, admin_cookies: dict, test_user: User
    ):
        response = await client.get(
            f"/admin/users/{test_user.id}/edit", cookies=admin_cookies
        )
        assert response.status_code == 200
        assert "Edit" in response.text

    async def test_users_update(
        self, client: AsyncClient, admin_cookies: dict, test_user: User
    ):
        cookies, token = _csrf_cookies(admin_cookies)
        response = await client.post(
            f"/admin/users/{test_user.id}",
            data=_csrf_data(token, full_name="Updated Name", max_referral_redemptions="10"),
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert f"/admin/users/{test_user.id}" in response.headers["location"]

    async def test_users_create_form(
        self, client: AsyncClient, admin_cookies: dict
    ):
        response = await client.get("/admin/users/new", cookies=admin_cookies)
        assert response.status_code == 200
        assert "New" in response.text

    async def test_users_filter_by_admin(
        self, client: AsyncClient, admin_cookies: dict, test_admin: User
    ):
        response = await client.get(
            "/admin/users/htmx/table?filter_is_admin=True",
            cookies=admin_cookies,
        )
        assert response.status_code == 200
        assert test_admin.full_name in response.text


@pytest.mark.asyncio
class TestAdminSessionViews:
    """Test session admin views with actual data."""

    async def test_sessions_list_with_data(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession, test_user: User
    ):
        session = Session(
            user_id=test_user.id,
            session_type=SessionType.CHECKIN.value,
            status=SessionStatus.ACTIVE.value,
            destination="Test Destination",
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()

        response = await client.get("/admin/sessions", cookies=admin_cookies)
        assert response.status_code == 200
        assert "Test Destination" in response.text

    async def test_sessions_filter_by_type(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession, test_user: User
    ):
        session = Session(
            user_id=test_user.id,
            session_type=SessionType.SOS.value,
            status=SessionStatus.ACTIVE.value,
            expected_return_time=datetime.now(UTC),
        )
        db_session.add(session)
        await db_session.commit()

        response = await client.get(
            "/admin/sessions/htmx/table?filter_session_type=sos",
            cookies=admin_cookies,
        )
        assert response.status_code == 200
        assert "sos" in response.text.lower()


@pytest.mark.asyncio
class TestAdminReadOnlyViews:
    """Test that read-only entities reject write operations."""

    @pytest.mark.parametrize(
        "path",
        [v.name_plural for v in ALL_VIEWS if v.read_only],
        ids=[v.name_plural for v in ALL_VIEWS if v.read_only],
    )
    async def test_read_only_no_new_route(
        self, client: AsyncClient, admin_cookies: dict, path: str
    ):
        response = await client.get(f"/admin/{path}/new", cookies=admin_cookies)
        # Should 404 or 405 since the route isn't registered
        assert response.status_code in (404, 405, 422)

    @pytest.mark.parametrize(
        "path",
        [v.name_plural for v in ALL_VIEWS if v.read_only],
        ids=[v.name_plural for v in ALL_VIEWS if v.read_only],
    )
    async def test_read_only_no_create_route(
        self, client: AsyncClient, admin_cookies: dict, path: str
    ):
        response = await client.post(
            f"/admin/{path}",
            data={"name": "test"},
            cookies=admin_cookies,
        )
        assert response.status_code in (404, 405, 422)


@pytest.mark.asyncio
class TestAdminDeleteFlow:
    """Test delete operations."""

    async def test_delete_redirects_to_list(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession, test_user: User
    ):
        session = Session(
            user_id=test_user.id,
            session_type=SessionType.CHECKIN.value,
            status=SessionStatus.COMPLETED.value,
            destination="Delete Me",
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        cookies, token = _csrf_cookies(admin_cookies)
        response = await client.post(
            f"/admin/sessions/{session.id}/delete",
            data=_csrf_data(token),
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "/admin/sessions" in response.headers["location"]


@pytest.mark.asyncio
class TestAdminPagination:
    """Test pagination in list views."""

    async def test_pagination_with_many_items(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession
    ):
        # Create 30 phone numbers to exceed page size of 25
        from app.models.phone_number import PhoneNumber

        for i in range(30):
            phone = PhoneNumber(number=f"+1555000{i:04d}")
            db_session.add(phone)
        await db_session.commit()

        response = await client.get("/admin/phone-numbers", cookies=admin_cookies)
        assert response.status_code == 200
        assert "Next →" in response.text

        # Page 2
        response = await client.get(
            "/admin/phone-numbers/htmx/table?page=2", cookies=admin_cookies
        )
        assert response.status_code == 200
        assert "← Prev" in response.text


@pytest.mark.asyncio
class TestAdminCSRF:
    """Test CSRF protection on admin POST routes."""

    async def test_post_without_csrf_cookie_returns_403(
        self, client: AsyncClient, admin_cookies: dict, test_user: User
    ):
        response = await client.post(
            f"/admin/users/{test_user.id}",
            data={"full_name": "Hacked"},
            cookies=admin_cookies,
            follow_redirects=False,
        )
        assert response.status_code == 403

    async def test_post_without_csrf_form_field_returns_403(
        self, client: AsyncClient, admin_cookies: dict, test_user: User
    ):
        cookies = {**admin_cookies, CSRF_COOKIE_NAME: generate_csrf_token()}
        response = await client.post(
            f"/admin/users/{test_user.id}",
            data={"full_name": "Hacked"},
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 403

    async def test_post_with_mismatched_csrf_returns_403(
        self, client: AsyncClient, admin_cookies: dict, test_user: User
    ):
        cookies = {**admin_cookies, CSRF_COOKIE_NAME: generate_csrf_token()}
        response = await client.post(
            f"/admin/users/{test_user.id}",
            data={CSRF_FORM_FIELD: generate_csrf_token(), "full_name": "Hacked"},
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 403

    async def test_delete_without_csrf_returns_403(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession, test_user: User
    ):
        session = Session(
            user_id=test_user.id,
            session_type=SessionType.CHECKIN.value,
            status=SessionStatus.COMPLETED.value,
            destination="Protected",
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        response = await client.post(
            f"/admin/sessions/{session.id}/delete",
            cookies=admin_cookies,
            follow_redirects=False,
        )
        assert response.status_code == 403

    async def test_form_page_sets_csrf_cookie(
        self, client: AsyncClient, admin_cookies: dict
    ):
        response = await client.get("/admin/users/new", cookies=admin_cookies)
        assert response.status_code == 200
        assert CSRF_COOKIE_NAME in response.cookies
        assert CSRF_FORM_FIELD in response.text

    async def test_detail_page_sets_csrf_cookie(
        self, client: AsyncClient, admin_cookies: dict, test_user: User
    ):
        response = await client.get(
            f"/admin/users/{test_user.id}", cookies=admin_cookies
        )
        assert response.status_code == 200
        assert CSRF_COOKIE_NAME in response.cookies
