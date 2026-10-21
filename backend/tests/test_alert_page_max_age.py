"""Never-resolved incidents: the public page goes neutral (owner decisions
2026-07-19). A session stuck MISSED/ALERTED past ALERT_PAGE_MAX_AGE_DAYS —
or admin-CANCELLED (closed false alarm) — stops serving the live incident
view: no location, photos, phone or Acknowledge, just "This alert is no
longer current. If {name} is still missing, contact law enforcement."
COMPLETED always wins (all-clear card), regardless of age.

Related: app/web/routes_web.py::_alert_view_context,
app/web/templates/alert_view.html, app/core/config.py
(ALERT_PAGE_MAX_AGE_DAYS), tests/test_never_resolved_retention.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.models.user import User
from tests.helpers import create_test_user

_PHONE = iter(f"+141555930{n:02d}" for n in range(1, 99))


async def _stuck_alert(
    db: AsyncSession,
    *,
    status: str = SessionStatus.MISSED.value,
    days_past_deadline: int = 8,
    alert_type: AlertType = AlertType.MISSED_SESSION,
) -> tuple[User, Alert]:
    owner = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Olive Owner"
    )
    contact = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Cara Contact"
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(days=days_past_deadline),
        destination="Ridge Trail",
        status=status,
        tz_offset_minutes=0,
        location_sharing_enabled=True,
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
            recorded_at=datetime.now(UTC) - timedelta(days=days_past_deadline),
        )
    )
    alert = Alert(
        session_id=session.id,
        sent_to_user_id=contact.id,
        alert_type=alert_type,
        status=AlertStatus.SENT,
        sent_at=datetime.now(UTC) - timedelta(days=days_past_deadline),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return owner, alert


@pytest.mark.asyncio
class TestAlertPageMaxAge:
    async def test_stale_missed_page_serves_no_pii(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner, alert = await _stuck_alert(db_session)

        resp = await client.get(f"/alerts/{alert.id}")
        assert resp.status_code == 200
        assert "no longer current" in resp.text
        assert "contact law enforcement" in resp.text
        # The live incident view — and its PII — is gone.
        assert "missed their check-in" not in resp.text
        assert owner.phone_number not in resp.text
        assert "maps.google.com" not in resp.text
        assert "Ridge Trail" not in resp.text
        assert "Acknowledge" not in resp.text
        assert 'http-equiv="refresh"' not in resp.text
        assert "may need help" not in resp.text  # <title> stays neutral too

    async def test_stale_alerted_page_goes_neutral_too(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, alert = await _stuck_alert(
            db_session, status=SessionStatus.ALERTED.value
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert "no longer current" in resp.text

    async def test_stale_sos_page_goes_neutral_identically(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, alert = await _stuck_alert(db_session, alert_type=AlertType.PANIC)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "no longer current" in resp.text
        assert "pressed SOS" not in resp.text

    async def test_fresh_incident_still_renders_the_live_page(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, alert = await _stuck_alert(db_session, days_past_deadline=6)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "no longer current" not in resp.text
        assert "missed their check-in" in resp.text
        assert "Acknowledge" in resp.text

    async def test_completed_always_wins_regardless_of_age(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, alert = await _stuck_alert(
            db_session,
            status=SessionStatus.COMPLETED.value,
            days_past_deadline=30,
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert "All clear" in resp.text
        assert "no longer current" not in resp.text

    async def test_cancelled_session_shows_the_neutral_card(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # An admin "close as false alarm" sets CANCELLED — the page must not
        # claim the owner marked themselves safe, and must not stay live.
        _, alert = await _stuck_alert(
            db_session,
            status=SessionStatus.CANCELLED.value,
            days_past_deadline=1,
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert "no longer current" in resp.text
        assert "marked themselves safe" not in resp.text

    async def test_stale_acknowledge_post_is_a_noop(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, alert = await _stuck_alert(db_session)

        resp = await client.post(f"/alerts/{alert.id}/acknowledge")
        assert resp.status_code == 303
        await db_session.refresh(alert)
        assert alert.status == AlertStatus.SENT
        assert alert.acknowledged_at is None
