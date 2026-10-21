"""Tests for CRUD changes (Commit 3).

- Atomic claim_for_processing / mark_as_alerted
- get_missed_sessions
- SessionReminder CRUD

(Failed-alert retry queries + mark_failed/mark_sms_sent moved to the
notification_deliveries outbox; see test_outbox_crud.py.)
"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import crud_session, crud_session_reminder
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from tests.helpers import create_test_user


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await create_test_user(db_session, phone_number="+14155556001")


@pytest_asyncio.fixture
async def contact(db_session: AsyncSession) -> User:
    return await create_test_user(db_session, phone_number="+14155556002")


async def _make_session(
    db: AsyncSession, owner: User, *, status: SessionStatus = SessionStatus.ACTIVE
) -> Session:
    s = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=5),
        status=status.value,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@pytest.mark.asyncio
class TestClaimForProcessing:
    async def test_claims_active_session(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(db_session, owner)

        claimed = await crud_session.claim_for_processing(
            db_session, session_id=session.id
        )
        assert claimed == session.id

        await db_session.refresh(session)
        assert session.status == SessionStatus.MISSED.value

    async def test_returns_none_if_already_claimed(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(db_session, owner, status=SessionStatus.MISSED)

        claimed = await crud_session.claim_for_processing(
            db_session, session_id=session.id
        )
        assert claimed is None

    async def test_returns_none_for_unknown_session(
        self, db_session: AsyncSession
    ):
        claimed = await crud_session.claim_for_processing(
            db_session, session_id=uuid4()
        )
        assert claimed is None

    async def test_does_not_claim_completed_session(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(
            db_session, owner, status=SessionStatus.COMPLETED
        )
        claimed = await crud_session.claim_for_processing(
            db_session, session_id=session.id
        )
        assert claimed is None
        await db_session.refresh(session)
        assert session.status == SessionStatus.COMPLETED.value


@pytest.mark.asyncio
class TestMarkAsAlerted:
    async def test_promotes_missed_to_alerted(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(db_session, owner, status=SessionStatus.MISSED)

        result = await crud_session.mark_as_alerted(db_session, session_id=session.id)
        assert result == session.id

        await db_session.refresh(session)
        assert session.status == SessionStatus.ALERTED.value

    async def test_only_promotes_from_missed(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(db_session, owner)  # ACTIVE
        result = await crud_session.mark_as_alerted(db_session, session_id=session.id)
        assert result is None


@pytest.mark.asyncio
class TestSessionRetryQueries:
    async def test_get_missed_sessions(
        self, db_session: AsyncSession, owner: User
    ):
        active = await _make_session(db_session, owner)
        owner2 = await create_test_user(db_session, phone_number="+14155556099")
        missed = await _make_session(db_session, owner2, status=SessionStatus.MISSED)

        results = await crud_session.get_missed_sessions(db_session)
        ids = {s.id for s in results}
        assert missed.id in ids
        assert active.id not in ids


@pytest.mark.asyncio
class TestSessionReminderCRUD:
    async def test_create_reminders_for_session(
        self, db_session: AsyncSession, owner: User
    ):
        session = Session(
            user_id=owner.id,
            session_type=SessionType.CHECKIN.value,
            expected_return_time=datetime.now(UTC) + timedelta(hours=2),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        # Only the at-deadline rung is server-scheduled now — it feeds the
        # "time's up" SMS, the one channel the client can't send. All reminder
        # PUSHES are client-scheduled local notifications (owner decision
        # 2026-07-18; ladder coverage in
        # mobile/services/notifications.reminderLadder.test.ts).
        rows = await crud_session_reminder.create_reminders_for_session(
            db_session,
            session_id=session.id,
            deadline=session.expected_return_time,
        )
        assert len(rows) == 1
        assert {r.minutes_before for r in rows} == {0}

    async def test_get_pending_returns_only_unsent_past_due(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(db_session, owner)
        now = datetime.now(UTC)

        from app.models.session_reminder import SessionReminder

        past_unsent = SessionReminder(
            session_id=session.id,
            fire_at=now - timedelta(minutes=5),
            minutes_before=10,
        )
        future_unsent = SessionReminder(
            session_id=session.id,
            fire_at=now + timedelta(minutes=10),
            minutes_before=15,
        )
        past_sent = SessionReminder(
            session_id=session.id,
            fire_at=now - timedelta(minutes=15),
            minutes_before=20,
            sent_at=now - timedelta(minutes=14),
        )
        db_session.add_all([past_unsent, future_unsent, past_sent])
        await db_session.commit()

        pending = await crud_session_reminder.get_pending(db_session)
        ids = {r.id for r in pending}
        assert past_unsent.id in ids
        assert future_unsent.id not in ids
        assert past_sent.id not in ids

    async def test_mark_sent_sets_sent_at(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(db_session, owner)
        from app.models.session_reminder import SessionReminder

        reminder = SessionReminder(
            session_id=session.id,
            fire_at=datetime.now(UTC) - timedelta(minutes=1),
            minutes_before=5,
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        await crud_session_reminder.mark_sent(db_session, reminder_id=reminder.id)
        await db_session.refresh(reminder)
        assert reminder.sent_at is not None

    async def test_delete_for_session_removes_all(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(db_session, owner)
        await crud_session_reminder.create_reminders_for_session(
            db_session,
            session_id=session.id,
            deadline=datetime.now(UTC) + timedelta(hours=2),
        )

        deleted = await crud_session_reminder.delete_for_session(
            db_session, session_id=session.id
        )
        assert deleted >= 1

        pending = await crud_session_reminder.get_pending(db_session)
        assert all(r.session_id != session.id for r in pending)
