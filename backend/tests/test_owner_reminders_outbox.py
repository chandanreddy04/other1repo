"""Owner reminders via the outbox: the server's ONLY reminder channel is the
at-deadline SMS. Every reminder PUSH (T-30/10/5/0) is a client-scheduled
local notification (owner decision 2026-07-18 — the device's clock fires
them in dead zones and backend outages); the ladder's behavior coverage
lives in mobile/services/notifications.reminderLadder.test.ts. Legacy
pre-deadline schedule rows are consumed without sending, and an extension
supersedes the stale at-deadline SMS delivery.

Related: app/services/session_tasks.py (send_owner_reminder,
         schedule_reminders_for_session).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus, SessionType
from app.services.session_tasks import (
    schedule_reminders_for_session,
    send_owner_reminder,
)
from tests.helpers import create_test_user


async def _active_session(db, owner) -> Session:
    s = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        status=SessionStatus.ACTIVE.value,
        expected_return_time=datetime.now(UTC) + timedelta(minutes=30),
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _deliveries(db, session_id, kind):
    return (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.session_id == session_id,
                    NotificationDelivery.kind == kind,
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
class TestOwnerRemindersOutbox:
    async def test_at_deadline_enqueues_sms_only(
        self, db_session: AsyncSession
    ):
        # The push for this rung is the client's local T-0 notification;
        # the server sends the one channel the client can't — SMS.
        owner = await create_test_user(
            db_session,
            phone_number="+14155596001",
            expo_push_token="ExponentPushToken[x]",
        )
        session = await _active_session(db_session, owner)

        assert await send_owner_reminder(db_session, str(session.id), 0) is True
        rows = await _deliveries(
            db_session, session.id, NotificationKind.OWNER_DEADLINE
        )
        channels = {r.channel for r in rows}
        assert channels == {DeliveryChannel.SMS}

    async def test_pre_deadline_rung_is_consumed_without_sending(
        self, db_session: AsyncSession
    ):
        # Legacy schedule rows (created before the client-side ladder
        # shipped) are marked done (True) but enqueue nothing — the device
        # covers those rungs locally.
        owner = await create_test_user(
            db_session,
            phone_number="+14155596002",
            expo_push_token="ExponentPushToken[x]",
        )
        session = await _active_session(db_session, owner)

        assert await send_owner_reminder(db_session, str(session.id), 30) is True
        assert not await _deliveries(
            db_session, session.id, NotificationKind.OWNER_REMINDER
        )

    async def test_non_active_session_enqueues_nothing(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(db_session, phone_number="+14155596003")
        session = await _active_session(db_session, owner)
        session.status = SessionStatus.COMPLETED.value
        await db_session.commit()

        assert await send_owner_reminder(db_session, str(session.id), 30) is False
        assert not await _deliveries(
            db_session, session.id, NotificationKind.OWNER_REMINDER
        )

    async def test_extension_supersedes_stale_deadline_sms(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session,
            phone_number="+14155596004",
            expo_push_token="ExponentPushToken[x]",
        )
        session = await _active_session(db_session, owner)
        await send_owner_reminder(db_session, str(session.id), 0)

        # Rescheduling (extension) supersedes the already-enqueued SMS.
        await schedule_reminders_for_session(
            db_session,
            session.id,
            datetime.now(UTC) + timedelta(hours=2),
        )
        await db_session.commit()

        [row] = await _deliveries(
            db_session, session.id, NotificationKind.OWNER_DEADLINE
        )
        assert row.status == DeliveryStatus.SUPERSEDED
