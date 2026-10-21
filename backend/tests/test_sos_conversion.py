"""SOS during a live check-in converts the SAME session (owner decision
2026-07-18): the outing escalates in place — type flips to SOS (PANIC alert
copy + page banner), the deadline becomes now, location sharing turns on —
so the circle's alert page carries everything gathered so far (destination,
outfit, photos, location trail). Only ACTIVE sessions convert; a session
already MISSED/ALERTED gets a fresh PANIC session instead (the circle was
already alerted for the miss and needs a distinct escalation).

Related: app/api/v1/endpoints/sessions.py::_create_sos_session,
.claude/rules/domain-sessions-alerts.md.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.alert import Alert, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus
from app.models.session_reminder import SessionReminder
from app.models.user import User
from tests.helpers import create_test_user

_PHONE = iter(f"+141555950{n:02d}" for n in range(1, 99))


def _auth(user: User) -> dict:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


async def _owner_with_member(db: AsyncSession) -> User:
    owner = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Olive Owner"
    )
    contact = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Cara Contact"
    )
    member = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=contact.phone_number_id,
        nickname=contact.full_name,
        status=ContactStatus.ACTIVE.value,
    )
    db.add(member)
    await db.commit()
    return owner


async def _checkin(
    db: AsyncSession, owner: User, *, status: str = SessionStatus.ACTIVE.value
) -> Session:
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) + timedelta(hours=2),
        destination="Riverside Trail",
        status=status,
        location_sharing_enabled=False,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
class TestSOSConversion:
    async def test_sos_converts_the_live_checkin_in_place(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner_with_member(db_session)
        checkin = await _checkin(db_session, owner)
        db_session.add(
            SessionReminder(
                session_id=checkin.id,
                fire_at=checkin.expected_return_time,
                minutes_before=0,
            )
        )
        await db_session.commit()

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(owner),
            json={"session_type": "sos"},
        )
        assert response.status_code == 201
        data = response.json()
        # Same session — escalated, not duplicated.
        assert data["id"] == str(checkin.id)
        assert data["session_type"] == "sos"
        # Everything gathered for the outing stays with it.
        assert data["destination"] == "Riverside Trail"
        # Emergency posture: location on, deadline accelerated to now,
        # dispatch already ran (status is past ACTIVE).
        assert data["location_sharing_enabled"] is True
        assert data["status"] in ("missed", "alerted")

        # No second session was created.
        count = len(
            (
                await db_session.execute(
                    select(Session).where(Session.user_id == owner.id)
                )
            )
            .scalars()
            .all()
        )
        assert count == 1

        # The circle got a PANIC alert (not a missed-check-in one).
        alerts = (
            (
                await db_session.execute(
                    select(Alert).where(Alert.session_id == checkin.id)
                )
            )
            .scalars()
            .all()
        )
        assert alerts and all(a.alert_type == AlertType.PANIC for a in alerts)

        # The old deadline's pending server reminder (T-0 SMS) was cleared.
        reminders = (
            (
                await db_session.execute(
                    select(SessionReminder).where(
                        SessionReminder.session_id == checkin.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert reminders == []

    async def test_sos_during_missed_session_creates_a_fresh_panic_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Once MISSED, the circle was already alerted for the miss — the SOS
        must be a distinct PANIC escalation, not an in-place rewrite."""
        owner = await _owner_with_member(db_session)
        missed = await _checkin(db_session, owner, status=SessionStatus.MISSED.value)

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(owner),
            json={"session_type": "sos"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["id"] != str(missed.id)
        assert data["session_type"] == "sos"

    async def test_sos_without_prior_session_still_creates_one(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner_with_member(db_session)

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(owner),
            json={"session_type": "sos"},
        )
        assert response.status_code == 201
        assert response.json()["session_type"] == "sos"
