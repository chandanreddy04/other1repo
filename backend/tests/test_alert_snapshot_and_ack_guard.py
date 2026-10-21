"""The terminal claim guard on alert acknowledgement.

acknowledge_alert() no-ops once the incident is over (alert RESOLVED or session
COMPLETED/CANCELLED): a late acknowledgement from any surface must not re-acknowledge
a resolved alert and broadcast after the all-clear. The public page shows
NOTHING about acknowledgements beyond the acknowledger's own checked,
grayed-out button (owner decision 2026-07-18 - identity and status stay
private within the circle).

The mobile GET /alerts, GET-unacknowledged-alerts and PUT
/alerts/{id}/acknowledge endpoints (formerly tested here, including the
circle-viewer session snapshot payload merged onto the mobile Alert
response) were removed 2026-09-22 (no in-app caller - Circle members use
mobile web only). That snapshot's fields (location gating, always-on
battery) keep independent coverage via the public alert page in
test_alert_page_parity.py, which reads the same services/circle_view.py
snapshot. "Still works during a live incident" keeps coverage via
acknowledge_alert() in test_alert_acknowledgement_sms.py and the public
page in test_no_app_contact_flows.py::TestPublicAlertPage::
test_claim_acknowledges_and_notifies_owner; "a no-op renders the real
terminal state" via test_public_claim_after_completion_renders_all_clear
below.

Related: app/services/alert_acknowledgement.py,
app/web/routes_web.py::_alert_view_context.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.models.user import User
from app.services.alert_acknowledgement import acknowledge_alert
from tests.helpers import create_test_user

_PHONE = iter(f"+141555990{n:02d}" for n in range(1, 99))


def _auth(user: User) -> dict:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


async def _owner_and_contact(db: AsyncSession) -> tuple[User, User]:
    owner = await create_test_user(db, phone_number=next(_PHONE), full_name="Ana Owner")
    contact = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Cara Contact"
    )
    return owner, contact


async def _session(
    db: AsyncSession,
    owner: User,
    *,
    status: str = SessionStatus.MISSED.value,
    location_sharing: bool = False,
    with_location: bool = False,
) -> Session:
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        destination="Central Park",
        status=status,
        tz_offset_minutes=0,
        location_sharing_enabled=location_sharing,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    if with_location:
        db.add(
            SessionUpdate(
                session_id=session.id,
                latitude=40.785,
                longitude=-73.968,
                battery_level=0.42,
                recorded_at=datetime.now(UTC),
            )
        )
        await db.commit()
        # expire_on_commit=False: re-select so the identity-mapped instance's
        # last_known_* column_propertys reflect the update we just inserted.
        await db.refresh(session)
    return session


async def _alert(
    db: AsyncSession,
    session: Session,
    contact: User,
    *,
    status: AlertStatus = AlertStatus.SENT,
) -> Alert:
    alert = Alert(
        session_id=session.id,
        sent_to_user_id=contact.id,
        alert_type=AlertType.MISSED_SESSION,
        status=status,
        sent_at=datetime.now(UTC),
        acknowledged_at=datetime.now(UTC)
        if status == AlertStatus.ACKNOWLEDGED
        else None,
        resolved_at=datetime.now(UTC) if status == AlertStatus.RESOLVED else None,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@pytest.mark.asyncio
class TestClaimTerminalGuard:
    async def test_claim_resolved_alert_is_a_noop(self, db_session: AsyncSession):
        owner, contact = await _owner_and_contact(db_session)
        session = await _session(
            db_session, owner, status=SessionStatus.COMPLETED.value
        )
        alert = await _alert(db_session, session, contact, status=AlertStatus.RESOLVED)

        await acknowledge_alert(db_session, alert=alert)
        await db_session.refresh(alert)
        assert alert.status == AlertStatus.RESOLVED
        assert alert.acknowledged_at is None

    async def test_claim_blocked_once_session_completed(self, db_session: AsyncSession):
        """Even a SENT alert (e.g. left untouched by resolve) can't be claimed
        after the session ended — no late 'on it' broadcast after all-clear."""
        owner, contact = await _owner_and_contact(db_session)
        session = await _session(
            db_session, owner, status=SessionStatus.COMPLETED.value
        )
        alert = await _alert(db_session, session, contact, status=AlertStatus.SENT)

        await acknowledge_alert(db_session, alert=alert)
        await db_session.refresh(alert)
        assert alert.status == AlertStatus.SENT
        assert alert.acknowledged_at is None

    async def test_public_claim_after_completion_renders_all_clear(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner, contact = await _owner_and_contact(db_session)
        session = await _session(
            db_session, owner, status=SessionStatus.COMPLETED.value
        )
        alert = await _alert(db_session, session, contact, status=AlertStatus.RESOLVED)

        response = await client.post(f"/alerts/{alert.id}/acknowledge")
        assert response.status_code == 303
        page = await client.get(response.headers["location"])
        assert "All clear" in page.text
        await db_session.refresh(alert)
        assert alert.status == AlertStatus.RESOLVED


@pytest.mark.asyncio
class TestAcknowledgementIsPrivateOnPublicPage:
    async def test_other_recipients_learn_nothing_from_the_page(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The page shows NOTHING about acknowledgements to other recipients
        (owner decision 2026-07-18 — identity and status stay private):
        after contact A acknowledges, contact B still sees their own active
        Acknowledge button and no mention of A."""
        owner, contact_a = await _owner_and_contact(db_session)
        contact_b = await create_test_user(
            db_session, phone_number=next(_PHONE), full_name="Ben Backup"
        )
        session = await _session(db_session, owner, status=SessionStatus.MISSED.value)
        await _alert(db_session, session, contact_a, status=AlertStatus.ACKNOWLEDGED)
        alert_b = await _alert(db_session, session, contact_b)

        response = await client.get(f"/alerts/{alert_b.id}")
        assert response.status_code == 200
        assert "Cara" not in response.text
        assert "✓ Acknowledged" not in response.text
        # B's own acknowledgement is still open.
        assert f"/alerts/{alert_b.id}/acknowledge" in response.text

    async def test_acknowledger_sees_only_the_checked_grayed_button(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The acknowledger's own feedback is the button state alone — no
        badge, no notice text."""
        owner, contact = await _owner_and_contact(db_session)
        contact_b = await create_test_user(
            db_session, phone_number=next(_PHONE), full_name="Ben Backup"
        )
        session = await _session(db_session, owner, status=SessionStatus.MISSED.value)
        alert = await _alert(
            db_session, session, contact, status=AlertStatus.ACKNOWLEDGED
        )
        await _alert(db_session, session, contact_b)

        response = await client.get(f"/alerts/{alert.id}")
        assert "✓ Acknowledged" in response.text
        # No form action for an already-acknowledged alert, no notice copy.
        assert f"/alerts/{alert.id}/acknowledge" not in response.text
        assert "on it" not in response.text
