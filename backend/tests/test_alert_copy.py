"""Differentiated circle-alert copy (SOS vs missed check-in).

Covers the 2026-07-02 flow-review decisions (docs/flow-review.md §4.3 B2/3.3):
an SOS (deliberate act) and a missed check-in (passive inference) must be
distinguishable to the recipient; the missed body renders the expected-return
time in the OWNER's local time via sessions.tz_offset_minutes and falls back
to time-free copy when no offset was captured; destination rides along when
available and battery only when critically low.

Related: app/services/session_tasks.py (_build_alert_content,
_format_local_time), app/services/notification_constants.py.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.alert import AlertType
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.services.session_tasks import _build_alert_content, _format_local_time
from tests.helpers import create_test_user


async def _make_session(db: AsyncSession, phone: str, **kwargs) -> Session:
    user = await create_test_user(db, phone_number=phone, full_name="Ana Test")
    session = Session(
        user_id=user.id,
        expected_return_time=kwargs.pop(
            "expected_return_time", datetime(2026, 7, 3, 5, 30, tzinfo=UTC)
        ),
        status=SessionStatus.MISSED.value,
        **kwargs,
    )
    db.add(session)
    await db.commit()
    # _build_alert_content reads session.user.phone_number (a @property over
    # user.phone) synchronously; commit() expires all attributes, so re-query
    # with everything eager-loaded (mirrors process_overdue's selectinload).
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.user).selectinload(User.phone))
        .where(Session.id == session.id)
    )
    return result.scalar_one()


class TestFormatLocalTime:
    def test_renders_local_clock_time(self):
        # 05:30 UTC at UTC-7 (PDT) = 10:30 PM the previous day.
        dt = datetime(2026, 7, 3, 5, 30, tzinfo=UTC)
        assert _format_local_time(dt, -420) == "10:30 PM"

    def test_no_leading_zero(self):
        dt = datetime(2026, 7, 3, 9, 5, tzinfo=UTC)
        assert _format_local_time(dt, 0) == "9:05 AM"

    def test_none_offset_returns_none(self):
        dt = datetime(2026, 7, 3, 5, 30, tzinfo=UTC)
        assert _format_local_time(dt, None) is None


@pytest.mark.asyncio
class TestBuildAlertContent:
    async def test_missed_body_with_local_time(self, db_session: AsyncSession):
        session = await _make_session(
            db_session, "+14155590001", tz_offset_minutes=-420
        )
        alert_type, body = _build_alert_content(session)
        assert alert_type == AlertType.MISSED_SESSION
        assert body.startswith("Made It Home: Ana Test hasn't checked in")
        assert "expected to be back by 10:30 PM" in body
        assert "Please check on them:" in body
        # Owner's phone, display-formatted, so the contact can call back.
        assert "(415) 559-0001" in body

    async def test_missed_body_falls_back_without_offset(
        self, db_session: AsyncSession
    ):
        session = await _make_session(db_session, "+14155590002")
        _, body = _build_alert_content(session)
        # Never render a UTC clock time — use the time-free variant.
        assert "hasn't checked in on time" in body
        assert "expected to be back by" not in body

    async def test_sos_body_is_distinct_and_urgent(self, db_session: AsyncSession):
        session = await _make_session(
            db_session,
            "+14155590003",
            session_type=SessionType.SOS,
        )
        alert_type, body = _build_alert_content(session)
        assert alert_type == AlertType.PANIC
        assert body.startswith("Made It Home EMERGENCY: Ana Test activated SOS")
        assert "needs help now" in body
        # SOS and missed copy must not be identical (flow-review B2).
        assert "hasn't checked in" not in body

    async def test_destination_and_low_battery_ride_along(
        self, db_session: AsyncSession
    ):
        session = await _make_session(
            db_session,
            "+14155590004",
            tz_offset_minutes=0,
            destination="Central Park",
            last_battery_level=0.04,
        )
        _, body = _build_alert_content(session)
        assert "They were headed to Central Park." in body
        # Battery only when critically low (LOW_BATTERY_ALERT_THRESHOLD) —
        # threshold cases live in test_battery_tracking.py.
        assert "Last known battery: 4%." in body

    async def test_degrades_gracefully_without_optional_data(
        self, db_session: AsyncSession
    ):
        session = await _make_session(db_session, "+14155590005")
        _, body = _build_alert_content(session)
        assert "headed to" not in body
        assert "battery" not in body.lower()
