"""Signed retention adjustment + terminal-session truth columns
(owner decisions 2026-07-19, session-summary exploration):

- PUT /sessions/{id}/retention accepts an optional {"days": ±7} body; no
  body keeps the historical single-extension behavior.
- Reductions only walk back extensions the owner personally added: clamped
  to the FLOOR = max(session end + SESSION_DATA_RETENTION_DAYS, now). Inside
  the original window the floor IS the original deletion date — a hostile
  phone-holder can never beat the evidence window, and there is deliberately
  no owner-facing "delete now".
- Session end anchor: actual_return_time (owner marked safe) or cancelled_at
  (admin close — the neutral timestamp that never claims the owner
  returned). Neither → reduction refused (legacy edge, extend-only).
- purged_at records when data deletion ACTUALLY ran (stamped inside
  purge_session_data, so the admin early-purge path is covered too).
- was_alerted (owner detail endpoint): did ANY alert ever fire — drives the
  summary screen's "Was shared with your Circle" vs "Nothing was shared".

Related: app/api/v1/endpoints/sessions.py, app/services/session_tasks.py,
app/web/routes_admin.py, tests/test_session_data_retention.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.models.user import User
from app.services.session_tasks import purge_session_data
from app.web.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, generate_csrf_token
from tests.helpers import create_test_user

_PHONE = iter(f"+141555950{n:02d}" for n in range(1, 99))

_RETENTION = timedelta(days=settings.SESSION_DATA_RETENTION_DAYS)
_STEP = timedelta(days=settings.RETENTION_EXTENSION_DAYS)


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _terminal_session(
    db: AsyncSession,
    user: User,
    *,
    ended_ago: timedelta = timedelta(hours=1),
    extensions: int = 0,
    status: str = SessionStatus.COMPLETED.value,
    cancelled: bool = False,
) -> Session:
    """A terminal session whose purge_after reflects `extensions` prior +7d
    extensions on top of the original (end + retention) date."""
    end = datetime.now(UTC) - ended_ago
    session = Session(
        user_id=user.id,
        expected_return_time=end - timedelta(hours=2),
        actual_return_time=None if cancelled else end,
        cancelled_at=end if cancelled else None,
        status=status,
        purge_after=end + _RETENTION + extensions * _STEP,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
class TestRetentionAdjustExtend:
    async def test_no_body_keeps_historical_extend_behavior(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        session = await _terminal_session(db_session, user)
        before = session.purge_after

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention", headers=_auth(user)
        )
        assert resp.status_code == 200
        await db_session.refresh(session)
        assert session.purge_after == before + _STEP

    async def test_explicit_positive_body_extends(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        session = await _terminal_session(db_session, user)
        before = session.purge_after

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention",
            headers=_auth(user),
            json={"days": settings.RETENTION_EXTENSION_DAYS},
        )
        assert resp.status_code == 200
        await db_session.refresh(session)
        assert session.purge_after == before + _STEP

    async def test_rejects_arbitrary_day_counts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        session = await _terminal_session(db_session, user)

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention",
            headers=_auth(user),
            json={"days": 3},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestRetentionAdjustReduce:
    async def test_reduce_walks_back_an_extension(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        session = await _terminal_session(db_session, user, extensions=2)
        before = session.purge_after

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention",
            headers=_auth(user),
            json={"days": -settings.RETENTION_EXTENSION_DAYS},
        )
        assert resp.status_code == 200
        await db_session.refresh(session)
        assert session.purge_after == before - _STEP

    async def test_reduce_clamps_at_the_original_deletion_date(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        # One extension: purge_after = original + 7d. A -7d lands exactly on
        # the original date; a second -7d must be refused (at minimum).
        session = await _terminal_session(db_session, user, extensions=1)
        original = session.actual_return_time + _RETENTION

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention",
            headers=_auth(user),
            json={"days": -settings.RETENTION_EXTENSION_DAYS},
        )
        assert resp.status_code == 200
        await db_session.refresh(session)
        assert session.purge_after == original

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention",
            headers=_auth(user),
            json={"days": -settings.RETENTION_EXTENSION_DAYS},
        )
        assert resp.status_code == 400
        await db_session.refresh(session)
        # Never below the original evidence window.
        assert session.purge_after == original

    async def test_floor_rises_to_now_once_the_original_date_has_passed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        # Ended 25 days ago, kept alive by 3 extensions → purge_after =
        # end + 7 + 21 = now + 3d. The original date is long past, so the
        # floor is NOW — a -7d (which would land at now - 4d) clamps to now
        # instead of scheduling deletion in the past.
        session = await _terminal_session(
            db_session, user, ended_ago=timedelta(days=25), extensions=3
        )

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention",
            headers=_auth(user),
            json={"days": -settings.RETENTION_EXTENSION_DAYS},
        )
        assert resp.status_code == 200
        await db_session.refresh(session)
        assert session.purge_after >= datetime.now(UTC) - timedelta(minutes=1)
        assert session.purge_after <= datetime.now(UTC) + timedelta(minutes=1)

    async def test_cancelled_sessions_reduce_from_cancelled_at(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        session = await _terminal_session(
            db_session,
            user,
            extensions=1,
            status=SessionStatus.CANCELLED.value,
            cancelled=True,
        )
        original = session.cancelled_at + _RETENTION

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention",
            headers=_auth(user),
            json={"days": -settings.RETENTION_EXTENSION_DAYS},
        )
        assert resp.status_code == 200
        await db_session.refresh(session)
        assert session.purge_after == original

    async def test_legacy_terminal_row_without_anchor_is_extend_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        # Legacy edge: terminal but neither actual_return_time nor
        # cancelled_at — the floor is unrecoverable, reduction refused.
        session = Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) - timedelta(hours=2),
            status=SessionStatus.CANCELLED.value,
            purge_after=datetime.now(UTC) + _RETENTION,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention",
            headers=_auth(user),
            json={"days": -settings.RETENTION_EXTENSION_DAYS},
        )
        assert resp.status_code == 400
        await db_session.refresh(session)
        assert session.purge_after is not None  # untouched


@pytest.mark.asyncio
class TestPurgedAtStamp:
    async def test_purge_session_data_stamps_purged_at(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        session = await _terminal_session(db_session, user)
        db_session.add(
            SessionUpdate(
                session_id=session.id,
                latitude=40.7,
                longitude=-73.9,
                recorded_at=datetime.now(UTC),
            )
        )
        await db_session.commit()
        assert session.purged_at is None

        storage = MagicMock()
        storage.delete_file = AsyncMock(return_value=True)
        await purge_session_data(db_session, session, storage)
        await db_session.commit()

        await db_session.refresh(session)
        assert session.purged_at is not None
        assert session.purged_at <= datetime.now(UTC)


@pytest.mark.asyncio
class TestCancelledAtStamp:
    async def test_close_false_alarm_stamps_cancelled_at_not_return_time(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        session = Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) - timedelta(days=9),
            status=SessionStatus.MISSED.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        token = generate_csrf_token()
        resp = await client.post(
            f"/admin/sessions/{session.id}/close-false-alarm",
            cookies={**admin_cookies, CSRF_COOKIE_NAME: token},
            data={CSRF_FORM_FIELD: token},
        )
        assert resp.status_code == 303

        await db_session.refresh(session)
        assert session.cancelled_at is not None
        # NEVER a return-time claim — the admin can't assert the owner
        # marked themselves safe.
        assert session.actual_return_time is None


@pytest.mark.asyncio
class TestWasAlerted:
    async def test_owner_detail_reports_whether_alerts_ever_fired(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number=next(_PHONE))
        contact = await create_test_user(db_session, phone_number=next(_PHONE))
        quiet = await _terminal_session(db_session, user)
        loud = await _terminal_session(db_session, user)
        db_session.add(
            Alert(
                session_id=loud.id,
                sent_to_user_id=contact.id,
                alert_type=AlertType.MISSED_SESSION,
                status=AlertStatus.RESOLVED,
                sent_at=datetime.now(UTC),
            )
        )
        await db_session.commit()

        quiet_resp = await client.get(
            f"/api/v1/sessions/{quiet.id}", headers=_auth(user)
        )
        loud_resp = await client.get(
            f"/api/v1/sessions/{loud.id}", headers=_auth(user)
        )
        assert quiet_resp.status_code == 200
        assert loud_resp.status_code == 200
        # "Nothing was shared with your Circle" vs "Was shared" — the summary
        # screen's honesty hinges on this flag.
        assert quiet_resp.json()["was_alerted"] is False
        assert loud_resp.json()["was_alerted"] is True
