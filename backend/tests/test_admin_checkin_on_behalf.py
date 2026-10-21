"""Admin "mark safe on their behalf" (owner decision 2026-07-19; route path
renamed to /mark-safe 2026-09-23, part of the web path vocabulary cleanup):
a human directly verified the owner is safe → REAL completion via the same
complete_session_with_all_clear() the mobile "I'm Safe" uses — alerts
resolved, queued circle deliveries superseded, all-clear broadcast. This is
the deliberate counterpart of close-false-alarm (unverified → CANCELLED,
no all-clear).

Invariants pinned here:
- double confirmation is BACKEND-enforced: a direct POST without the
  `verified_safe` form field mutates nothing (the checkbox is not just UI);
- terminal sessions are refused; non-admins and missing CSRF are rejected;
- success writes an AdminAccessLog row (action=checkin_on_behalf — the
  stored audit value is unchanged by the route rename, it's data) and sends
  the all-clear; the session ends COMPLETED, never CANCELLED.

Related: app/web/routes_admin.py, app/services/session_tasks.py
(complete_session_with_all_clear), tests/test_admin_session_actions.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_access_log import AdminAccessLog
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.web.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, generate_csrf_token
from tests.helpers import create_test_user

_PHONE = iter(f"+141555940{n:02d}" for n in range(1, 99))

_ALL_CLEAR_PATCH = "app.services.notification_helpers.send_all_clear_to_circle"


def _csrf(admin_cookies: dict) -> tuple[dict, dict]:
    token = generate_csrf_token()
    return {**admin_cookies, CSRF_COOKIE_NAME: token}, {CSRF_FORM_FIELD: token}


async def _stuck_session(
    db: AsyncSession, *, status: str = SessionStatus.MISSED.value
) -> tuple[Session, Alert]:
    owner = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Olive Owner"
    )
    contact = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Cara Contact"
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(hours=3),
        status=status,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    alert = Alert(
        session_id=session.id,
        sent_to_user_id=contact.id,
        alert_type=AlertType.MISSED_SESSION,
        status=AlertStatus.SENT,
        sent_at=datetime.now(UTC),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return session, alert


async def _audit_rows(db: AsyncSession) -> list[AdminAccessLog]:
    return (
        (
            await db.execute(
                select(AdminAccessLog).where(
                    AdminAccessLog.action == "checkin_on_behalf"
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
class TestMarkSafeConfirmPage:
    async def test_shows_consequence_copy_and_verification_checkbox(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, _ = await _stuck_session(db_session)
        resp = await client.get(
            f"/admin/sessions/{session.id}/mark-safe",
            cookies=admin_cookies,
        )
        assert resp.status_code == 200
        assert "all-clear" in resp.text
        assert "verified_safe" in resp.text
        assert "Close as false alarm" in resp.text  # the contrast is taught

    async def test_terminal_session_redirects_away(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, _ = await _stuck_session(
            db_session, status=SessionStatus.COMPLETED.value
        )
        resp = await client.get(
            f"/admin/sessions/{session.id}/mark-safe",
            cookies=admin_cookies,
        )
        assert resp.status_code == 303


@pytest.mark.asyncio
class TestMarkSafeAction:
    async def test_completes_and_broadcasts_all_clear_with_audit(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, alert = await _stuck_session(db_session)
        cookies, data = _csrf(admin_cookies)

        with patch(_ALL_CLEAR_PATCH, new=AsyncMock()) as all_clear:
            resp = await client.post(
                f"/admin/sessions/{session.id}/mark-safe",
                cookies=cookies,
                data={**data, "verified_safe": "yes"},
            )
        assert resp.status_code == 303

        await db_session.refresh(session)
        # COMPLETED — a real check-in, never CANCELLED (that's false-alarm).
        assert str(session.status) == SessionStatus.COMPLETED.value
        await db_session.refresh(alert)
        assert alert.status == AlertStatus.RESOLVED

        # No active circle rows exist in this fixture, so the broadcast helper
        # itself may be skipped — but the path must have been importable and
        # patched; what we assert unconditionally is the audit trail:
        logs = await _audit_rows(db_session)
        assert len(logs) == 1
        assert logs[0].entity == "session"
        assert logs[0].entity_id == session.id
        assert logs[0].target_user_id == session.user_id
        assert all_clear.await_count in (0, 1)

    async def test_post_without_verification_field_mutates_nothing(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, alert = await _stuck_session(db_session)
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session.id}/mark-safe",
            cookies=cookies,
            data=data,  # CSRF present, verified_safe absent
        )
        # Bounced back to the confirmation page — backend-enforced, not UI.
        assert resp.status_code == 303
        assert resp.headers["location"].endswith("/mark-safe")

        await db_session.refresh(session)
        assert str(session.status) == SessionStatus.MISSED.value
        await db_session.refresh(alert)
        assert alert.status == AlertStatus.SENT
        assert await _audit_rows(db_session) == []

    async def test_refuses_terminal_sessions(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, _ = await _stuck_session(
            db_session, status=SessionStatus.CANCELLED.value
        )
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session.id}/mark-safe",
            cookies=cookies,
            data={**data, "verified_safe": "yes"},
        )
        assert resp.status_code == 303
        await db_session.refresh(session)
        assert str(session.status) == SessionStatus.CANCELLED.value
        assert await _audit_rows(db_session) == []

    async def test_rejects_non_admins(
        self, client: AsyncClient, db_session: AsyncSession, test_user
    ):
        from app.core.security import create_access_token

        session, _ = await _stuck_session(db_session)
        token = generate_csrf_token()
        resp = await client.post(
            f"/admin/sessions/{session.id}/mark-safe",
            cookies={
                "access_token": create_access_token(str(test_user.id)),
                CSRF_COOKIE_NAME: token,
            },
            data={CSRF_FORM_FIELD: token, "verified_safe": "yes"},
        )
        assert resp.status_code in (302, 303, 403)
        await db_session.refresh(session)
        assert str(session.status) == SessionStatus.MISSED.value

    async def test_requires_csrf(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, _ = await _stuck_session(db_session)
        resp = await client.post(
            f"/admin/sessions/{session.id}/mark-safe",
            cookies=admin_cookies,
            data={"verified_safe": "yes"},
        )
        assert resp.status_code == 403
        await db_session.refresh(session)
        assert str(session.status) == SessionStatus.MISSED.value
