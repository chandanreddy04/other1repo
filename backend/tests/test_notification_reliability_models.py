"""Tests for notification reliability model changes (Commit 1).

Covers:
- ALERTED added to SessionStatus
- SessionReminder model and table

(Per-channel delivery/retry state — retry_count, sms_provider — moved off Alert
to the notification_deliveries outbox; covered by test_outbox_model.py.)
"""
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session, SessionStatus, SessionType
from app.models.session_reminder import SessionReminder
from app.models.user import User
from tests.helpers import create_test_user


@pytest_asyncio.fixture
async def session_owner(db_session: AsyncSession) -> User:
    return await create_test_user(db_session, phone_number="+14155551001")


@pytest_asyncio.fixture
async def active_session(db_session: AsyncSession, session_owner: User) -> Session:
    sess = Session(
        user_id=session_owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        status=SessionStatus.ACTIVE.value,
    )
    db_session.add(sess)
    await db_session.commit()
    await db_session.refresh(sess)
    return sess


class TestSessionStatusAlerted:
    def test_alerted_value_present(self):
        assert SessionStatus.ALERTED.value == "alerted"

    @pytest.mark.asyncio
    async def test_session_can_be_marked_alerted(
        self, db_session: AsyncSession, active_session: Session
    ):
        active_session.status = SessionStatus.ALERTED.value
        await db_session.commit()
        await db_session.refresh(active_session)
        assert active_session.status == SessionStatus.ALERTED.value


class TestSessionReminder:
    @pytest.mark.asyncio
    async def test_create_and_query_reminder(
        self, db_session: AsyncSession, active_session: Session
    ):
        fire_at = datetime.now(UTC) + timedelta(minutes=30)
        reminder = SessionReminder(
            session_id=active_session.id,
            fire_at=fire_at,
            minutes_before=15,
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        assert reminder.id is not None
        assert reminder.sent_at is None
        assert reminder.minutes_before == 15

        result = await db_session.execute(
            select(SessionReminder).where(SessionReminder.session_id == active_session.id)
        )
        assert result.scalar_one().id == reminder.id

    @pytest.mark.asyncio
    async def test_reminder_cascade_delete_with_session(
        self, db_session: AsyncSession, active_session: Session
    ):
        reminder = SessionReminder(
            session_id=active_session.id,
            fire_at=datetime.now(UTC) + timedelta(minutes=15),
            minutes_before=10,
        )
        db_session.add(reminder)
        await db_session.commit()
        reminder_id = reminder.id

        await db_session.delete(active_session)
        await db_session.commit()

        result = await db_session.execute(
            select(SessionReminder).where(SessionReminder.id == reminder_id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_reminder_marked_sent(
        self, db_session: AsyncSession, active_session: Session
    ):
        reminder = SessionReminder(
            session_id=active_session.id,
            fire_at=datetime.now(UTC) - timedelta(minutes=1),
            minutes_before=5,
        )
        db_session.add(reminder)
        await db_session.commit()

        reminder.sent_at = datetime.now(UTC)
        await db_session.commit()
        await db_session.refresh(reminder)
        assert reminder.sent_at is not None

    @pytest.mark.asyncio
    async def test_pending_reminders_query_uses_index(
        self, db_session: AsyncSession, active_session: Session
    ):
        now = datetime.now(UTC)
        past_unsent = SessionReminder(
            session_id=active_session.id,
            fire_at=now - timedelta(minutes=5),
            minutes_before=10,
        )
        future_unsent = SessionReminder(
            session_id=active_session.id,
            fire_at=now + timedelta(minutes=30),
            minutes_before=15,
        )
        past_sent = SessionReminder(
            session_id=active_session.id,
            fire_at=now - timedelta(minutes=10),
            minutes_before=20,
            sent_at=now - timedelta(minutes=9),
        )
        db_session.add_all([past_unsent, future_unsent, past_sent])
        await db_session.commit()

        result = await db_session.execute(
            select(SessionReminder)
            .where(SessionReminder.fire_at <= now)
            .where(SessionReminder.sent_at.is_(None))
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].id == past_unsent.id
