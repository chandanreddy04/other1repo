"""GET /sessions/{id} exposes alert_acknowledged — server truth for "claimed".

When a circle member claims an alert ("I'm on it"), the owner's surfaces
(active-session screen, lock-screen Live Activity) must be able to say
"someone is on their way" from server truth, never a guess. The session poll
carries a computed alert_acknowledged flag: True iff any alert for THIS
session is ACKNOWLEDGED. Everywhere else the schema keeps the fail-safe
False default.

Related: app/api/v1/endpoints/sessions.py (get_session),
app/crud/alert.py (has_acknowledged_alert), app/schemas/session.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.models.user import User
from tests.helpers import create_test_user


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _missed_session(db: AsyncSession, user: User) -> Session:
    session = Session(
        user_id=user.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=SessionStatus.MISSED.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _alert(
    db: AsyncSession, session: Session, recipient: User, status: AlertStatus
) -> Alert:
    alert = Alert(
        session_id=session.id,
        sent_to_user_id=recipient.id,
        alert_type=AlertType.MISSED_SESSION,
        message="test alert",
        status=status,
        sent_at=datetime.now(UTC),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@pytest.mark.asyncio
class TestSessionAlertAcknowledged:
    async def test_defaults_false_with_no_alerts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155567001")
        session = await _missed_session(db_session, user)

        r = await client.get(f"/api/v1/sessions/{session.id}", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["alert_acknowledged"] is False

    async def test_false_while_alerts_only_sent(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155567002")
        contact = await create_test_user(db_session, phone_number="+14155567003")
        session = await _missed_session(db_session, user)
        await _alert(db_session, session, contact, AlertStatus.SENT)

        r = await client.get(f"/api/v1/sessions/{session.id}", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["alert_acknowledged"] is False

    async def test_true_once_any_alert_acknowledged(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155567004")
        contact = await create_test_user(db_session, phone_number="+14155567005")
        contact2 = await create_test_user(db_session, phone_number="+14155567006")
        session = await _missed_session(db_session, user)
        await _alert(db_session, session, contact, AlertStatus.SENT)
        await _alert(db_session, session, contact2, AlertStatus.ACKNOWLEDGED)

        r = await client.get(f"/api/v1/sessions/{session.id}", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["alert_acknowledged"] is True

    async def test_scoped_to_the_requested_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # An acknowledged alert on ANOTHER of the user's sessions must not
        # leak into this one.
        user = await create_test_user(db_session, phone_number="+14155567007")
        contact = await create_test_user(db_session, phone_number="+14155567008")
        other = await _missed_session(db_session, user)
        await _alert(db_session, other, contact, AlertStatus.ACKNOWLEDGED)
        session = await _missed_session(db_session, user)

        r = await client.get(f"/api/v1/sessions/{session.id}", headers=_auth(user))
        assert r.status_code == 200
        assert r.json()["alert_acknowledged"] is False
