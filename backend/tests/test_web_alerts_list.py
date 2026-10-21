"""GET /alerts — the Circle member's alert list is LIST ONLY (owner decision
2026-09-23): a row shows who/what/when/status and links to the alert detail
page (GET /alerts/{alert_id}); no inline location/contact/photo, no map, no
poll, no inline acknowledge.

Covers the fix for the previous version, which compared alert_type/status
against uppercase strings ('MISSED_SESSION', 'EMERGENCY', 'DELIVERED',
'ACKNOWLEDGED') that never matched the stored lowercase enum values (so no
acknowledge button ever rendered and every alert was labelled "Location
Alert"), and which read session fields directly instead of the
circle-viewer snapshot (leaking coordinates even with location sharing off,
raw phone, raw S3 photo URL).

Also pins the never-resolved-incident rule on this surface
(.claude/rules/domain-sessions-alerts.md): a CANCELLED session, or one stuck
MISSED/ALERTED past ALERT_PAGE_MAX_AGE_DAYS, lists as "No longer current"
and drops out of the unacknowledged-alert badge count.

Related: app/web/routes_web.py (alerts_page, _alert_list_row,
_alert_status_label, _is_no_longer_current), app/crud/alert.py
(get_unacknowledged_alerts, stale_incident_cutoff),
app/services/session_tasks.py (_format_local_datetime),
app/web/routes_htmx_profile.py (the deleted poll/acknowledge/
location-history routes).
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.crud.alert import crud_alert
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.models.user import User
from app.services.session_tasks import _format_local_datetime
from tests.helpers import create_test_user

# 07:51 UTC at a -420 min (UTC-7) offset is 12:51 AM local, same day.
_FIXED_SENT_AT = datetime(2026, 9, 23, 7, 51, tzinfo=UTC)
_FIXED_SENT_AT_LOCAL = "Sep 23, 12:51 AM"


def _cookie(user: User) -> dict:
    return {"access_token": create_access_token(str(user.id))}


async def _make_session(
    db: AsyncSession,
    owner: User,
    *,
    status: SessionStatus = SessionStatus.MISSED,
    location_sharing_enabled: bool = False,
    deadline_ago: timedelta = timedelta(minutes=30),
    outfit_photo_url: str | None = None,
) -> Session:
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - deadline_ago,
        status=status,
        tz_offset_minutes=-420,
        location_sharing_enabled=location_sharing_enabled,
        outfit_photo_url=outfit_photo_url,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _make_alert(
    db: AsyncSession,
    *,
    session: Session,
    recipient: User,
    alert_type: AlertType,
    status: AlertStatus,
    sent_at: datetime | None = None,
) -> Alert:
    alert = Alert(
        session_id=session.id,
        sent_to_user_id=recipient.id,
        alert_type=alert_type,
        status=status,
        message="test alert body",
        sent_at=sent_at or datetime.now(UTC),
        acknowledged_at=(
            datetime.now(UTC) if status == AlertStatus.ACKNOWLEDGED else None
        ),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


def _row_html(body: str, alert_id: uuid.UUID) -> str:
    """The HTML for one row's <a> block, so assertions can check a specific
    row's labels instead of just "the label appears somewhere on the page"
    (several rows share labels like "New")."""
    match = re.search(rf'<a href="/alerts/{alert_id}".*?</a>', body, re.DOTALL)
    assert match, f"no row rendered for alert {alert_id}\n{body}"
    return match.group(0)


_STALE = timedelta(days=settings.ALERT_PAGE_MAX_AGE_DAYS, hours=1)
_NOT_YET_STALE = timedelta(days=settings.ALERT_PAGE_MAX_AGE_DAYS - 1)


@pytest.mark.asyncio
class TestAlertsListRows:
    async def test_real_enum_values_render_honest_labels(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155591101", full_name="Olive Owner"
        )
        member = await create_test_user(
            db_session, phone_number="+14155591102", full_name="Mel Member"
        )

        # The (session_id, sent_to_user_id, alert_type) unique constraint means
        # two alerts of the same type for the same recipient need distinct
        # sessions — one session per row here.
        async def alert_on(status, alert_type, alert_status, **session_kw):
            return await _make_alert(
                db_session,
                session=await _make_session(
                    db_session, owner, status=status, **session_kw
                ),
                recipient=member,
                alert_type=alert_type,
                status=alert_status,
            )

        panic_delivered = await alert_on(
            SessionStatus.ALERTED, AlertType.PANIC, AlertStatus.DELIVERED
        )
        missed_sent = await alert_on(
            SessionStatus.MISSED, AlertType.MISSED_SESSION, AlertStatus.SENT
        )
        missed_ack = await alert_on(
            SessionStatus.MISSED, AlertType.MISSED_SESSION, AlertStatus.ACKNOWLEDGED
        )
        failed = await alert_on(
            SessionStatus.MISSED, AlertType.MISSED_SESSION, AlertStatus.FAILED
        )
        reminder = await alert_on(
            SessionStatus.MISSED, AlertType.REMINDER, AlertStatus.SENT
        )
        # Realistic mark-safe: resolve_session_alerts sets RESOLVED AND the
        # session is COMPLETED — reads "All clear", never "Resolved".
        panic_marked_safe = await alert_on(
            SessionStatus.COMPLETED, AlertType.PANIC, AlertStatus.RESOLVED
        )
        # COMPLETED wins over the alert's own (acknowledged) status.
        ack_then_safe = await alert_on(
            SessionStatus.COMPLETED, AlertType.MISSED_SESSION, AlertStatus.ACKNOWLEDGED
        )
        # Admin "close as false alarm": CANCELLED + alerts RESOLVED.
        cancelled = await alert_on(
            SessionStatus.CANCELLED, AlertType.MISSED_SESSION, AlertStatus.RESOLVED
        )
        # Never-resolved: still MISSED past ALERT_PAGE_MAX_AGE_DAYS.
        stale = await alert_on(
            SessionStatus.MISSED,
            AlertType.MISSED_SESSION,
            AlertStatus.SENT,
            deadline_ago=_STALE,
        )
        stale_ack = await alert_on(
            SessionStatus.ALERTED,
            AlertType.MISSED_SESSION,
            AlertStatus.ACKNOWLEDGED,
            deadline_ago=_STALE,
        )
        # One day short of the cutoff: still a live incident.
        not_yet_stale = await alert_on(
            SessionStatus.MISSED,
            AlertType.MISSED_SESSION,
            AlertStatus.SENT,
            deadline_ago=_NOT_YET_STALE,
        )

        resp = await client.get("/alerts", cookies=_cookie(member))
        assert resp.status_code == 200
        body = resp.text

        expected = {
            panic_delivered.id: ("SOS alert", "New"),
            missed_sent.id: ("Missed check-in alert", "New"),
            missed_ack.id: ("Missed check-in alert", "Acknowledged"),
            failed.id: ("Missed check-in alert", "Delivery failed"),
            reminder.id: ("Reminder", "New"),
            panic_marked_safe.id: ("SOS alert", "All clear"),
            ack_then_safe.id: ("Missed check-in alert", "All clear"),
            cancelled.id: ("Missed check-in alert", "No longer current"),
            stale.id: ("Missed check-in alert", "No longer current"),
            stale_ack.id: ("Missed check-in alert", "No longer current"),
            not_yet_stale.id: ("Missed check-in alert", "New"),
        }
        for alert_id, (type_label, status_label) in expected.items():
            row = _row_html(body, alert_id)
            assert type_label in row, (alert_id, row)
            assert f">{status_label}</span>" in row, (alert_id, status_label, row)
            assert "Olive" in row

        # Retired labels never render.
        assert ">Resolved<" not in body
        assert ">Closed<" not in body

    async def test_sent_time_is_owner_local_date_and_time(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155591151", full_name="Tia Owner"
        )
        member = await create_test_user(
            db_session, phone_number="+14155591152", full_name="Ron Member"
        )
        alert = await _make_alert(
            db_session,
            session=await _make_session(db_session, owner),
            recipient=member,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
            sent_at=_FIXED_SENT_AT,
        )

        resp = await client.get("/alerts", cookies=_cookie(member))
        assert resp.status_code == 200
        row = _row_html(resp.text, alert.id)
        assert _FIXED_SENT_AT_LOCAL in row
        assert "7:51" not in row  # never the UTC clock time

    async def test_no_session_detail_leaks_onto_the_list(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155591201", full_name="Pat Owner"
        )
        member = await create_test_user(
            db_session, phone_number="+14155591202", full_name="Cam Member"
        )
        photo_url = "https://bucket.s3.amazonaws.com/outfits/secret-photo-key.jpg"
        session = await _make_session(
            db_session,
            owner,
            location_sharing_enabled=True,
            outfit_photo_url=photo_url,
        )
        db_session.add(
            SessionUpdate(
                session_id=session.id,
                latitude=40.785091,
                longitude=-73.968285,
                battery_level=0.55,
                recorded_at=datetime.now(UTC),
            )
        )
        await db_session.commit()
        await _make_alert(
            db_session,
            session=session,
            recipient=member,
            alert_type=AlertType.PANIC,
            status=AlertStatus.DELIVERED,
        )

        resp = await client.get("/alerts", cookies=_cookie(member))
        assert resp.status_code == 200
        body = resp.text

        assert "40.785091" not in body
        assert "-73.968285" not in body
        assert "+14155591201" not in body
        assert "5591201" not in body
        assert "secret-photo-key" not in body
        assert "s3.amazonaws.com" not in body
        assert "test alert body" not in body  # the message is detail-page only
        assert "maps.google.com" not in body
        assert "leaflet" not in body.lower()
        assert "hx-post" not in body

    async def test_lists_only_the_viewers_own_alerts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155591251", full_name="Ada Owner"
        )
        member = await create_test_user(
            db_session, phone_number="+14155591252", full_name="Bo Member"
        )
        other = await create_test_user(
            db_session, phone_number="+14155591253", full_name="Cy Other"
        )
        session = await _make_session(db_session, owner)
        mine = await _make_alert(
            db_session,
            session=session,
            recipient=member,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
        )
        theirs = await _make_alert(
            db_session,
            session=session,
            recipient=other,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
        )

        resp = await client.get("/alerts", cookies=_cookie(member))
        assert resp.status_code == 200
        assert f"/alerts/{mine.id}" in resp.text
        assert str(theirs.id) not in resp.text

    async def test_empty_state(self, client: AsyncClient, db_session: AsyncSession):
        member = await create_test_user(
            db_session, phone_number="+14155591301", full_name="No Alerts Member"
        )
        resp = await client.get("/alerts", cookies=_cookie(member))
        assert resp.status_code == 200
        assert "No Alerts Yet" in resp.text


class TestFormatLocalDatetime:
    def test_renders_local_date_and_unpadded_time(self):
        assert _format_local_datetime(_FIXED_SENT_AT, -420) == _FIXED_SENT_AT_LOCAL

    def test_local_date_can_differ_from_utc_date(self):
        # 03:05 UTC on Sep 23 is 8:05 PM on Sep 22 at UTC-7.
        dt = datetime(2026, 9, 23, 3, 5, tzinfo=UTC)
        assert _format_local_datetime(dt, -420) == "Sep 22, 8:05 PM"

    def test_no_offset_means_no_time(self):
        assert _format_local_datetime(_FIXED_SENT_AT, None) is None


@pytest.mark.asyncio
class TestGetUnacknowledgedAlertsExcludesEndedIncidents:
    async def test_resolved_and_ended_session_alerts_are_excluded(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155591401", full_name="Uma Owner"
        )
        member = await create_test_user(
            db_session, phone_number="+14155591402", full_name="Nia Member"
        )

        live_session = await _make_session(db_session, owner)
        completed_session = await _make_session(
            db_session, owner, status=SessionStatus.COMPLETED
        )
        cancelled_session = await _make_session(
            db_session, owner, status=SessionStatus.CANCELLED
        )

        still_open = await _make_alert(
            db_session,
            session=live_session,
            recipient=member,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
        )
        await _make_alert(
            db_session,
            session=live_session,
            recipient=member,
            alert_type=AlertType.PANIC,
            status=AlertStatus.RESOLVED,
        )
        await _make_alert(
            db_session,
            session=completed_session,
            recipient=member,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
        )
        await _make_alert(
            db_session,
            session=cancelled_session,
            recipient=member,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
        )
        await _make_alert(
            db_session,
            session=await _make_session(db_session, owner),
            recipient=member,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.ACKNOWLEDGED,
        )

        unacknowledged = await crud_alert.get_unacknowledged_alerts(
            db_session, user_id=member.id
        )

        assert [a.id for a in unacknowledged] == [still_open.id]
        # contains_eager + joinedload: owner is loaded without another query.
        assert unacknowledged[0].session.user.full_name == "Uma Owner"

    async def test_never_resolved_incidents_past_the_cutoff_are_excluded(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155591451", full_name="Vic Owner"
        )
        member = await create_test_user(
            db_session, phone_number="+14155591452", full_name="Wes Member"
        )

        for status in (SessionStatus.MISSED, SessionStatus.ALERTED):
            await _make_alert(
                db_session,
                session=await _make_session(
                    db_session, owner, status=status, deadline_ago=_STALE
                ),
                recipient=member,
                alert_type=AlertType.MISSED_SESSION,
                status=AlertStatus.SENT,
            )
        recent = await _make_alert(
            db_session,
            session=await _make_session(
                db_session,
                owner,
                status=SessionStatus.ALERTED,
                deadline_ago=_NOT_YET_STALE,
            ),
            recipient=member,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
        )

        unacknowledged = await crud_alert.get_unacknowledged_alerts(
            db_session, user_id=member.id
        )

        assert [a.id for a in unacknowledged] == [recent.id]


@pytest.mark.asyncio
class TestDeletedHtmxAlertRoutesAreGone:
    async def test_alerts_check_is_gone(self, client: AsyncClient):
        resp = await client.get("/htmx/alerts/check", follow_redirects=False)
        assert resp.status_code == 404

    async def test_acknowledge_is_gone(self, client: AsyncClient):
        resp = await client.post(
            f"/htmx/alerts/{uuid.uuid4()}/acknowledge", follow_redirects=False
        )
        assert resp.status_code == 404

    async def test_location_history_is_gone(self, client: AsyncClient):
        resp = await client.get(
            f"/htmx/sessions/{uuid.uuid4()}/location-history",
            follow_redirects=False,
        )
        assert resp.status_code == 404
