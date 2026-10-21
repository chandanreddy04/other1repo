"""Admin per-entry data management (owner decision 2026-07-19): scoped
deletion of individual captured entries — one ping's coordinates, one ping's
battery.

Security invariants pinned here:
- admin-only (non-admins rejected) and CSRF-protected, like every admin POST;
- ownership-chain check: a crafted cross-session entity ID is a silent no-op
  (nothing mutated, nothing audit-logged), never a cross-tenant delete;
- every successful action writes an AdminAccessLog row in the same commit;
- a ping carrying location AND battery is cleared field-scoped (the other
  reading survives); the row is dropped once both readings are empty.

Related: app/web/routes_admin.py, tests/test_admin_session_actions.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_access_log import AdminAccessLog
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.web.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, generate_csrf_token
from tests.helpers import create_test_user

_PHONE = iter(f"+141555930{n:02d}" for n in range(1, 99))


def _csrf(admin_cookies: dict) -> tuple[dict, dict]:
    token = generate_csrf_token()
    return {**admin_cookies, CSRF_COOKIE_NAME: token}, {CSRF_FORM_FIELD: token}


async def _session_with_data(
    db: AsyncSession,
    *,
    status: str = SessionStatus.ACTIVE.value,
    latitude: float | None = 40.7,
    battery: float | None = 0.5,
) -> tuple[Session, SessionUpdate]:
    owner = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Olive Owner"
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) + timedelta(hours=2),
        status=status,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    update = SessionUpdate(
        session_id=session.id,
        latitude=latitude,
        longitude=-73.9 if latitude is not None else None,
        battery_level=battery,
        battery_state="unplugged" if battery is not None else None,
        recorded_at=datetime.now(UTC),
    )
    db.add(update)
    await db.commit()
    await db.refresh(update)
    return session, update


async def _audit_rows(db: AsyncSession, action: str) -> list[AdminAccessLog]:
    return (
        (
            await db.execute(
                select(AdminAccessLog).where(AdminAccessLog.action == action)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
class TestClearLocationEntry:
    async def test_clears_coords_but_keeps_battery(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, update = await _session_with_data(db_session)
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session.id}/updates/{update.id}/clear-location",
            cookies=cookies,
            data=data,
        )
        assert resp.status_code == 303

        await db_session.refresh(update)
        assert update.latitude is None
        assert update.longitude is None
        # The battery reading on the same row survives — scoped clearing.
        assert update.battery_level == 0.5

        logs = await _audit_rows(db_session, "clear_location_entry")
        assert len(logs) == 1
        assert logs[0].entity_id == update.id

    async def test_rejects_non_admins(
        self, client: AsyncClient, db_session: AsyncSession, test_user
    ):
        from app.core.security import create_access_token

        session, update = await _session_with_data(db_session)
        token = generate_csrf_token()
        resp = await client.post(
            f"/admin/sessions/{session.id}/updates/{update.id}/clear-location",
            cookies={
                "access_token": create_access_token(str(test_user.id)),
                CSRF_COOKIE_NAME: token,
            },
            data={CSRF_FORM_FIELD: token},
        )
        assert resp.status_code in (302, 303, 403)
        await db_session.refresh(update)
        assert update.latitude is not None
        assert await _audit_rows(db_session, "clear_location_entry") == []

    async def test_row_dropped_once_both_readings_are_empty(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, update = await _session_with_data(db_session, battery=None)
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session.id}/updates/{update.id}/clear-location",
            cookies=cookies,
            data=data,
        )
        assert resp.status_code == 303
        assert await db_session.get(SessionUpdate, update.id) is None

    async def test_cross_session_update_id_is_a_silent_noop(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session_a, _ = await _session_with_data(db_session)
        _, update_b = await _session_with_data(db_session)
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session_a.id}/updates/{update_b.id}/clear-location",
            cookies=cookies,
            data=data,
        )
        assert resp.status_code == 303

        await db_session.refresh(update_b)
        assert update_b.latitude is not None
        assert await _audit_rows(db_session, "clear_location_entry") == []


@pytest.mark.asyncio
class TestClearBatteryEntry:
    async def test_clears_battery_but_keeps_coords(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, update = await _session_with_data(db_session)
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session.id}/updates/{update.id}/clear-battery",
            cookies=cookies,
            data=data,
        )
        assert resp.status_code == 303

        await db_session.refresh(update)
        assert update.battery_level is None
        assert update.battery_state is None
        assert update.latitude == 40.7

        logs = await _audit_rows(db_session, "clear_battery_entry")
        assert len(logs) == 1

    async def test_rejects_non_admins(
        self, client: AsyncClient, db_session: AsyncSession, test_user
    ):
        from app.core.security import create_access_token

        session, update = await _session_with_data(db_session)
        token = generate_csrf_token()
        resp = await client.post(
            f"/admin/sessions/{session.id}/updates/{update.id}/clear-battery",
            cookies={
                "access_token": create_access_token(str(test_user.id)),
                CSRF_COOKIE_NAME: token,
            },
            data={CSRF_FORM_FIELD: token},
        )
        assert resp.status_code in (302, 303, 403)
        await db_session.refresh(update)
        assert update.battery_level == 0.5
        assert await _audit_rows(db_session, "clear_battery_entry") == []

    async def test_battery_only_row_is_dropped_entirely(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, update = await _session_with_data(db_session, latitude=None)
        cookies, data = _csrf(admin_cookies)

        resp = await client.post(
            f"/admin/sessions/{session.id}/updates/{update.id}/clear-battery",
            cookies=cookies,
            data=data,
        )
        assert resp.status_code == 303
        assert await db_session.get(SessionUpdate, update.id) is None

    async def test_requires_csrf(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        session, update = await _session_with_data(db_session)
        resp = await client.post(
            f"/admin/sessions/{session.id}/updates/{update.id}/clear-battery",
            cookies=admin_cookies,
        )
        assert resp.status_code == 403
        await db_session.refresh(update)
        assert update.battery_level == 0.5
