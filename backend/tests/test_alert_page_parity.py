"""Public alert page (/alerts/{id}): SOS and missed-check-in show the same
information, differing only in the trigger banner near the top.

A circle member who received the alert SMS must be able to — on either page —
contact the owner, see location (if shared), battery, the destination, expected
check-in time, and last device ping, and (when more than
one contact was notified) acknowledge the alert. Guards the parity the owner asked
for so the SOS page can't silently drift to showing less than the missed page.

Related: app/web/routes_web.py::_alert_view_context, templates/alert_view.html,
test_no_app_contact_flows.py::TestPublicAlertPage (the base cases).
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from tests.helpers import create_test_user

_PHONE = iter(f"+141555970{n:02d}" for n in range(1, 99))


async def _build(
    db: AsyncSession,
    *,
    alert_type: AlertType = AlertType.MISSED_SESSION,
    recipients: int = 2,
    location: bool = False,
    location_sharing: bool = True,
    status: str = SessionStatus.MISSED.value,
) -> Alert:
    """Build a session + N alerts and return the first alert (its id is the
    page token). Optionally attach a device update carrying location +
    battery."""
    owner = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Ana Owner"
    )
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

    if location:
        db.add(
            SessionUpdate(
                session_id=session.id,
                latitude=40.785,
                longitude=-73.968,
                battery_level=0.42,
                recorded_at=datetime.now(UTC),
            )
        )

    first_alert: Alert | None = None
    for _ in range(recipients):
        contact = await create_test_user(
            db, phone_number=next(_PHONE), full_name="Cody Contact"
        )
        alert = Alert(
            session_id=session.id,
            sent_to_phone_id=contact.phone_number_id,
            alert_type=alert_type,
            status=AlertStatus.SENT,
            message="test",
        )
        db.add(alert)
        await db.commit()
        await db.refresh(alert)
        if first_alert is None:
            first_alert = alert
    assert first_alert is not None
    return first_alert


@pytest.mark.asyncio
class TestLiveRefreshParity:
    async def test_refresh_tag_identical_on_live_sos_and_missed_pages(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # The auto-refresh (server-truth re-render for a page left open) must
        # ride BOTH live pages identically — parity invariant.
        missed = await _build(db_session, recipients=2)
        sos = await _build(db_session, alert_type=AlertType.PANIC, recipients=2)
        for alert in (missed, sos):
            resp = await client.get(f"/alerts/{alert.id}")
            assert 'http-equiv="refresh"' in resp.text

    async def test_refresh_stops_once_the_incident_is_over(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(
            db_session, recipients=2, status=SessionStatus.COMPLETED.value
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert 'http-equiv="refresh"' not in resp.text


@pytest.mark.asyncio
class TestClaimVisibility:
    async def test_ack_shown_even_for_a_single_notified_contact(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Owner decision 2026-07-19 (reverses the old >1 coordination gate):
        # the acknowledgement is the OWNER's "a human saw this" confirmation,
        # equally valuable for the common 1-contact circle.
        alert = await _build(db_session, recipients=1)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "Acknowledge" in resp.text

    async def test_ack_shown_for_multiple_notified_contacts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, recipients=3)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "Acknowledge" in resp.text


@pytest.mark.asyncio
class TestSharedDataRespectsToggles:
    async def test_battery_always_shown_no_toggle(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Battery has no sharing toggle — it's always shown when there's a
        # reading (permission-free and safety-critical).
        alert = await _build(db_session, location=True)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "Last known battery" in resp.text

    async def test_location_hidden_when_sharing_disabled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, location=True, location_sharing=False)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "maps.google.com" not in resp.text

    async def test_location_and_battery_and_ping_shown_when_enabled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, location=True)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "maps.google.com" in resp.text
        assert "42%" in resp.text
        assert "Last pinged" in resp.text


@pytest.mark.asyncio
class TestSosMissedParity:
    async def test_sos_and_missed_show_the_same_shared_data(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        common = {"recipients": 2, "location": True}
        missed = await _build(
            db_session, alert_type=AlertType.MISSED_SESSION, **common
        )
        sos = await _build(db_session, alert_type=AlertType.PANIC, **common)

        missed_text = (await client.get(f"/alerts/{missed.id}")).text
        sos_text = (await client.get(f"/alerts/{sos.id}")).text

        # Both surface the full shared picture — including the ways to reach
        # the owner (call + text)...
        for token in (
            "tel:",  # call the owner
            "sms:",  # text the owner
            "Central Park",
            "maps.google.com",
            "42%",
            "Last pinged",
            "Acknowledge",
            "call 911",
        ):
            assert token in missed_text, f"missed page missing {token}"
            assert token in sos_text, f"sos page missing {token}"

        # ...and differ only in the trigger banner near the top.
        assert "missed their check-in" in missed_text
        assert "pressed SOS" in sos_text
        assert "pressed SOS" not in missed_text
        assert "missed their check-in" not in sos_text
