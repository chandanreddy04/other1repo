"""Tests for admin audit log (models/admin_access_log.py, admin_views.py logging)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_access_log import AdminAccessLog
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.web.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, generate_csrf_token


def _csrf_cookies(admin_cookies: dict) -> tuple[dict, str]:
    token = generate_csrf_token()
    return {**admin_cookies, CSRF_COOKIE_NAME: token}, token


@pytest.mark.asyncio
class TestAuditLogOnDetailView:
    async def test_detail_view_creates_audit_row(
        self,
        client: AsyncClient,
        admin_cookies: dict,
        test_admin: User,
        test_user: User,
        db_session: AsyncSession,
    ):
        response = await client.get(
            f"/admin/users/{test_user.id}", cookies=admin_cookies
        )
        assert response.status_code == 200

        result = await db_session.execute(
            select(AdminAccessLog).where(
                AdminAccessLog.admin_user_id == test_admin.id,
                AdminAccessLog.entity == "user",
                AdminAccessLog.action == "view_detail",
                AdminAccessLog.entity_id == test_user.id,
            )
        )
        log = result.scalar_one_or_none()
        assert log is not None
        assert log.target_user_id == test_user.id

    async def test_detail_session_derives_target_user(
        self,
        client: AsyncClient,
        admin_cookies: dict,
        test_admin: User,
        db_session: AsyncSession,
        test_user: User,
    ):
        session = Session(
            user_id=test_user.id,
            session_type=SessionType.CHECKIN.value,
            status=SessionStatus.ACTIVE.value,
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        response = await client.get(
            f"/admin/sessions/{session.id}", cookies=admin_cookies
        )
        assert response.status_code == 200

        result = await db_session.execute(
            select(AdminAccessLog).where(
                AdminAccessLog.entity == "session",
                AdminAccessLog.action == "view_detail",
                AdminAccessLog.entity_id == session.id,
            )
        )
        log = result.scalar_one()
        assert log.target_user_id == test_user.id


@pytest.mark.asyncio
class TestAuditLogOnListView:
    async def test_list_view_creates_audit_row(
        self,
        client: AsyncClient,
        admin_cookies: dict,
        test_admin: User,
        db_session: AsyncSession,
    ):
        response = await client.get("/admin/users", cookies=admin_cookies)
        assert response.status_code == 200

        result = await db_session.execute(
            select(AdminAccessLog).where(
                AdminAccessLog.admin_user_id == test_admin.id,
                AdminAccessLog.entity == "user",
                AdminAccessLog.action == "list",
            )
        )
        log = result.scalar_one()
        assert log.entity_id is None
        assert log.target_user_id is None


@pytest.mark.asyncio
class TestAuditLogOnEdit:
    async def test_edit_creates_audit_row(
        self,
        client: AsyncClient,
        admin_cookies: dict,
        test_admin: User,
        test_user: User,
        db_session: AsyncSession,
    ):
        cookies, token = _csrf_cookies(admin_cookies)
        response = await client.post(
            f"/admin/users/{test_user.id}",
            data={CSRF_FORM_FIELD: token, "full_name": "Edited Name"},
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 303

        result = await db_session.execute(
            select(AdminAccessLog).where(
                AdminAccessLog.admin_user_id == test_admin.id,
                AdminAccessLog.entity == "user",
                AdminAccessLog.action == "edit",
                AdminAccessLog.entity_id == test_user.id,
            )
        )
        log = result.scalar_one()
        assert log.target_user_id == test_user.id


@pytest.mark.asyncio
class TestAuditLogOnDelete:
    async def test_delete_creates_audit_row(
        self,
        client: AsyncClient,
        admin_cookies: dict,
        test_admin: User,
        db_session: AsyncSession,
        test_user: User,
    ):
        session = Session(
            user_id=test_user.id,
            session_type=SessionType.CHECKIN.value,
            status=SessionStatus.COMPLETED.value,
            destination="Audit Delete Test",
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        cookies, token = _csrf_cookies(admin_cookies)
        response = await client.post(
            f"/admin/sessions/{session.id}/delete",
            data={CSRF_FORM_FIELD: token},
            cookies=cookies,
            follow_redirects=False,
        )
        assert response.status_code == 303

        result = await db_session.execute(
            select(AdminAccessLog).where(
                AdminAccessLog.entity == "session",
                AdminAccessLog.action == "delete",
                AdminAccessLog.entity_id == session.id,
            )
        )
        log = result.scalar_one()
        assert log.target_user_id == test_user.id
        assert log.admin_user_id == test_admin.id


@pytest.mark.asyncio
class TestAuditLogAdminView:
    async def test_audit_log_list_returns_200(
        self, client: AsyncClient, admin_cookies: dict
    ):
        response = await client.get("/admin/admin-access-logs", cookies=admin_cookies)
        assert response.status_code == 200

    async def test_audit_log_is_read_only(
        self, client: AsyncClient, admin_cookies: dict
    ):
        response = await client.get("/admin/admin-access-logs/new", cookies=admin_cookies)
        assert response.status_code in (404, 405, 422)

    async def test_audit_log_shows_entries(
        self,
        client: AsyncClient,
        admin_cookies: dict,
        test_admin: User,
        test_user: User,
        db_session: AsyncSession,
    ):
        # Trigger an audit entry by viewing a user detail
        await client.get(f"/admin/users/{test_user.id}", cookies=admin_cookies)

        response = await client.get("/admin/admin-access-logs", cookies=admin_cookies)
        assert response.status_code == 200
        assert "view_detail" in response.text
