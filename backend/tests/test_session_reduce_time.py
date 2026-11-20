"""Reducing an active session's deadline via PUT /sessions/{id}/extend.

A negative `minutes_to_extend` brings the return time IN — letting an owner
undo an accidental over-extend (previously impossible: the schema was
`gt=0`, so the deadline could only move later). The endpoint rejects a
reduction that would push the deadline to/into the past, which would
otherwise instantly trip the circle-alert pipeline.

Related: app/api/v1/endpoints/sessions.py (extend_session),
app/schemas/session.py (SessionExtend).
"""

from datetime import UTC, datetime, timedelta

import pytest
from dateutil.parser import isoparse
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.session import Session, SessionStatus
from app.models.user import User
from tests.helpers import create_test_user


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _active_session(
    db: AsyncSession, user: User, *, minutes_ahead: int
) -> Session:
    session = Session(
        user_id=user.id,
        expected_return_time=datetime.now(UTC) + timedelta(minutes=minutes_ahead),
        status=SessionStatus.ACTIVE.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
class TestReduceSessionTime:
    async def test_reduce_brings_deadline_in(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155562001")
        session = await _active_session(db_session, user, minutes_ahead=120)
        original = session.expected_return_time

        r = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": -60},
        )
        assert r.status_code == 200
        new_return = isoparse(r.json()["expected_return_time"])
        assert abs((new_return - (original - timedelta(minutes=60))).total_seconds()) < 2

    async def test_reduce_past_now_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # 5 min left; cutting 60 would land in the past — and any result
        # under the 5-minute floor (owner decision 2026-11-19) is rejected.
        user = await create_test_user(db_session, phone_number="+14155562002")
        session = await _active_session(db_session, user, minutes_ahead=5)
        original = session.expected_return_time

        r = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": -60},
        )
        assert r.status_code == 400
        assert "5 minutes" in r.json()["detail"]

        refetched = await client.get(
            f"/api/v1/sessions/{session.id}", headers=_auth(user)
        )
        assert isoparse(refetched.json()["expected_return_time"]) == original

    async def test_reduce_leaving_at_least_the_floor_ok(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # 100 min left; cutting 60 leaves 40 — above the 5-minute floor.
        user = await create_test_user(db_session, phone_number="+14155562003")
        session = await _active_session(db_session, user, minutes_ahead=100)

        r = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": -60},
        )
        assert r.status_code == 200

    async def test_reduce_below_the_floor_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # 33 min left; cutting 30 would leave 3 — under the floor → 400.
        user = await create_test_user(db_session, phone_number="+14155562005")
        session = await _active_session(db_session, user, minutes_ahead=33)

        r = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": -30},
        )
        assert r.status_code == 400
        assert "5 minutes" in r.json()["detail"]

    async def test_extend_still_works(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Positive delta is unchanged by the reduce support.
        user = await create_test_user(db_session, phone_number="+14155562004")
        session = await _active_session(db_session, user, minutes_ahead=60)
        original = session.expected_return_time

        r = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": 30},
        )
        assert r.status_code == 200
        new_return = isoparse(r.json()["expected_return_time"])
        assert abs((new_return - (original + timedelta(minutes=30))).total_seconds()) < 2
