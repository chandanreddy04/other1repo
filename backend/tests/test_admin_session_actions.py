"""Admin stuck-session actions (owner decisions 2026-07-19): closure and
disposal of a never-resolved session are HUMAN decisions.

- close-false-alarm: MISSED/ALERTED → CANCELLED (never COMPLETED — the
  all-clear card claims "marked themselves safe", which an admin cannot
  assert), alerts resolved, retention clock started, NO all-clear broadcast.
- purge-data: immediately deletes the captured data via the same
  purge_session_data() the retention cleanup uses; refuses ACTIVE sessions.

Related: app/web/routes_admin.py, app/services/session_tasks.py,
tests/test_never_resolved_retention.py (why nothing purges automatically).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.notification_delivery import NotificationKind
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.web.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, generate_csrf_token
from tests.helpers import create_test_user

_PHONE = iter(f"+141555910{n:02d}" for n in range(1, 99))


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
        expected_return_time=datetime.now(UTC) - timedelta(days=10),
        status=status,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    db.add(
        SessionUpdate(
            session_id=session.id,
            latitude=40.7,
            longitude=-73.9,
            battery_level=0.5,
            recorded_at=datetime.now(UTC),
        )
    )
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


def _csrf(admin_cookies: dict) -> tuple[dict, dict]:
    token = generate_csrf_token()
    return {**admin_cookies, CSRF_COOKIE_NAME: token}, {CSRF_FORM_FIELD: token}


@pytest.mark.asyncio
class TestCloseFalseAlarm:
    async def test_closes_a_stuck_session_honestly(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, alert = await _stuck_session(db_session)
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session.id}/close-false-alarm",
            cookies=cookies,
            data=data,
        )
        assert resp.status_code == 303

        await db_session.refresh(session)
        # CANCELLED, never COMPLETED — no false "marked themselves safe".
        assert str(session.status) == SessionStatus.CANCELLED.value
        assert session.purge_after is not None
        await db_session.refresh(alert)
        assert alert.status == AlertStatus.RESOLVED

        # No all-clear broadcast was enqueued.
        rows = (
            (
                await db_session.execute(
                    select(
                        # any ALL_CLEAR delivery for this session
                        Session.id
                    ).where(Session.id == session.id)
                )
            )
            .scalars()
            .all()
        )
        from app.models.notification_delivery import NotificationDelivery

        all_clear = (
            (
                await db_session.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.session_id == session.id,
                        NotificationDelivery.kind == NotificationKind.ALL_CLEAR,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert all_clear == []
        assert rows  # session row itself still exists (data retained)

        # The public page now shows the neutral card.
        page = await client.get(f"/alerts/{alert.id}")
        assert "no longer current" in page.text
        assert "marked themselves safe" not in page.text

    async def test_refuses_an_active_session(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, _ = await _stuck_session(
            db_session, status=SessionStatus.ACTIVE.value
        )
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session.id}/close-false-alarm",
            cookies=cookies,
            data=data,
        )
        assert resp.status_code == 303
        await db_session.refresh(session)
        assert str(session.status) == SessionStatus.ACTIVE.value

    async def test_requires_csrf(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, _ = await _stuck_session(db_session)
        resp = await client.post(
            f"/admin/sessions/{session.id}/close-false-alarm",
            cookies=admin_cookies,
        )
        assert resp.status_code == 403


@pytest.mark.asyncio
class TestPurgeDataNow:
    async def test_purges_a_stuck_sessions_data(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, _ = await _stuck_session(db_session)
        cookies, data = _csrf(admin_cookies)

        with patch(
            "app.web.routes_admin.BlobStorageService",
            return_value=MagicMock(),
        ):
            resp = await client.post(
                f"/admin/sessions/{session.id}/purge-data",
                cookies=cookies,
                data=data,
            )
        assert resp.status_code == 303

        rows = (
            (
                await db_session.execute(
                    select(SessionUpdate).where(
                        SessionUpdate.session_id == session.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

    async def test_never_purges_a_live_session(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, _ = await _stuck_session(
            db_session, status=SessionStatus.ACTIVE.value
        )
        cookies, data = _csrf(admin_cookies)

        with patch(
            "app.web.routes_admin.BlobStorageService",
            return_value=MagicMock(),
        ):
            resp = await client.post(
                f"/admin/sessions/{session.id}/purge-data",
                cookies=cookies,
                data=data,
            )
        assert resp.status_code == 303

        rows = (
            (
                await db_session.execute(
                    select(SessionUpdate).where(
                        SessionUpdate.session_id == session.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows, "an ACTIVE session's data must never be purged"

    async def test_rejects_non_admins(
        self, client: AsyncClient, db_session: AsyncSession, test_user
    ):
        from app.core.security import create_access_token

        session, _ = await _stuck_session(db_session)
        cookies = {"access_token": create_access_token(str(test_user.id))}
        token = generate_csrf_token()
        resp = await client.post(
            f"/admin/sessions/{session.id}/purge-data",
            cookies={**cookies, CSRF_COOKIE_NAME: token},
            data={CSRF_FORM_FIELD: token},
        )
        assert resp.status_code in (302, 303, 403)
        rows = (
            (
                await db_session.execute(
                    select(SessionUpdate).where(
                        SessionUpdate.session_id == session.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows
