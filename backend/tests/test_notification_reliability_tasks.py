"""Tests for rewritten session_tasks.py (Commit 4).

Covers:
- process_overdue with atomic claim + per-member dispatch + mark_as_alerted
- process_missed_session retry
- process_pending_reminders
- schedule_reminders_for_session
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import crud_alert
from app.models.alert import SMSProvider
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus, SessionType
from app.models.session_reminder import SessionReminder
from app.models.user import User
from app.services.session_tasks import (
    process_missed_session,
    process_overdue,
    process_pending_reminders,
    schedule_reminders_for_session,
)
from app.services.sms import SMSResult
from tests.helpers import create_test_user


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await create_test_user(
        db_session,
        phone_number="+14155559001",
        full_name="Session Owner",
        expo_push_token="ExponentPushToken[owner_token]",
    )


@pytest_asyncio.fixture
async def contact(db_session: AsyncSession) -> User:
    return await create_test_user(
        db_session,
        phone_number="+14155559002",
        full_name="Circle Contact",
        expo_push_token="ExponentPushToken[contact_token]",
    )


async def _make_session(
    db: AsyncSession,
    owner: User,
    *,
    status: SessionStatus = SessionStatus.ACTIVE,
    overdue: bool = True,
) -> Session:
    delta = timedelta(minutes=-5) if overdue else timedelta(hours=1)
    s = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) + delta,
        status=status.value,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _add_circle_member(
    db: AsyncSession, owner: User, contact: User
) -> CircleOfTrustMember:
    member = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=contact.phone_number_id,
        nickname=contact.full_name,
        status=ContactStatus.ACTIVE.value,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest.mark.asyncio
class TestProcessOverdue:
    @patch("app.services.notification_outbox.ExpoPushNotificationService.send_notification", new_callable=AsyncMock)
    @patch("app.services.notification_outbox.sms_opt_out.gated_send_sms", new_callable=AsyncMock)
    @patch("app.services.notification_helpers.send_session_expired_notification", new_callable=AsyncMock)
    async def test_claims_and_dispatches(
        self,
        mock_notify_owner,
        mock_sms,
        mock_push,
        db_session: AsyncSession,
        owner: User,
        contact: User,
    ):
        mock_push.return_value = {
            "status": "error",
            "ok_tokens": [],
            "dead_tokens": [],
            "ticket_ids": {},
        }
        mock_sms.return_value = SMSResult(
            success=True, message_id="SM1", provider=SMSProvider.TWILIO
        )
        session = await _make_session(db_session, owner)
        await _add_circle_member(db_session, owner, contact)

        result = await process_overdue(db_session, session.id)

        # SMS reached the member → session promoted (push may fail independently).
        assert result["alerts_sent"] is True
        await db_session.refresh(session)
        assert session.status == SessionStatus.ALERTED.value
        mock_notify_owner.assert_awaited_once()

    @patch("app.services.notification_outbox.ExpoPushNotificationService.send_notification", new_callable=AsyncMock)
    @patch("app.services.notification_outbox.sms_opt_out.gated_send_sms", new_callable=AsyncMock)
    async def test_does_not_double_claim(
        self,
        mock_sms,
        mock_push,
        db_session: AsyncSession,
        owner: User,
        contact: User,
    ):
        session = await _make_session(
            db_session, owner, status=SessionStatus.MISSED
        )
        result = await process_overdue(db_session, session.id)
        assert result["alerts_sent"] is False
        mock_sms.assert_not_awaited()

    @patch("app.services.notification_outbox.ExpoPushNotificationService.send_notification", new_callable=AsyncMock)
    @patch("app.services.notification_outbox.sms_opt_out.gated_send_sms", new_callable=AsyncMock)
    async def test_stays_missed_on_dispatch_failure(
        self,
        mock_sms,
        mock_push,
        db_session: AsyncSession,
        owner: User,
        contact: User,
    ):
        mock_sms.return_value = SMSResult(success=False, error="fail")
        mock_push.side_effect = Exception("push down")
        session = await _make_session(db_session, owner)
        await _add_circle_member(db_session, owner, contact)

        result = await process_overdue(db_session, session.id)

        assert result["alerts_sent"] is False
        await db_session.refresh(session)
        assert session.status == SessionStatus.MISSED.value

    @patch("app.services.notification_outbox.ExpoPushNotificationService.send_notification", new_callable=AsyncMock)
    @patch("app.services.notification_outbox.sms_opt_out.gated_send_sms", new_callable=AsyncMock)
    async def test_records_sms_provider_on_alert(
        self,
        mock_sms,
        mock_push,
        db_session: AsyncSession,
        owner: User,
        contact: User,
    ):
        mock_push.return_value = {
            "status": "error",
            "ok_tokens": [],
            "dead_tokens": [],
            "ticket_ids": {},
        }
        mock_sms.return_value = SMSResult(
            success=True, message_id="SNS1", provider=SMSProvider.SNS
        )
        session = await _make_session(db_session, owner)
        await _add_circle_member(db_session, owner, contact)

        await process_overdue(db_session, session.id)

        alerts = await crud_alert.get_session_alerts(
            db_session, session_id=session.id
        )
        assert len(alerts) == 1
        # Provider + message id now live on the SMS delivery row, not the Alert.
        from app.models.notification_delivery import (
            DeliveryChannel,
            NotificationDelivery,
        )

        sms_delivery = (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.alert_id == alerts[0].id,
                    NotificationDelivery.channel == DeliveryChannel.SMS,
                )
            )
        ).scalar_one()
        assert sms_delivery.provider == SMSProvider.SNS.value
        assert sms_delivery.provider_message_id == "SNS1"


@pytest.mark.asyncio
class TestProcessMissedSession:
    @patch("app.services.notification_outbox.ExpoPushNotificationService.send_notification", new_callable=AsyncMock)
    @patch("app.services.notification_outbox.sms_opt_out.gated_send_sms", new_callable=AsyncMock)
    async def test_retries_missed_session(
        self,
        mock_sms,
        mock_push,
        db_session: AsyncSession,
        owner: User,
        contact: User,
    ):
        mock_push.return_value = {
            "status": "error",
            "ok_tokens": [],
            "dead_tokens": [],
            "ticket_ids": {},
        }
        mock_sms.return_value = SMSResult(
            success=True, message_id="SM2", provider=SMSProvider.TWILIO
        )
        session = await _make_session(
            db_session, owner, status=SessionStatus.MISSED
        )
        await _add_circle_member(db_session, owner, contact)

        result = await process_missed_session(db_session, session.id)

        assert result["alerts_sent"] is True
        await db_session.refresh(session)
        assert session.status == SessionStatus.ALERTED.value



@pytest.mark.asyncio
class TestProcessPendingReminders:
    @patch("app.services.session_tasks.send_owner_reminder", new_callable=AsyncMock)
    async def test_sends_pending_reminders(
        self,
        mock_reminder,
        db_session: AsyncSession,
        owner: User,
    ):
        mock_reminder.return_value = True
        session = await _make_session(db_session, owner, overdue=False)
        reminder = SessionReminder(
            session_id=session.id,
            fire_at=datetime.now(UTC) - timedelta(minutes=1),
            minutes_before=15,
        )
        db_session.add(reminder)
        await db_session.commit()
        await db_session.refresh(reminder)

        count = await process_pending_reminders(db_session)

        assert count >= 1
        await db_session.refresh(reminder)
        assert reminder.sent_at is not None

    @patch("app.services.session_tasks.send_owner_reminder", new_callable=AsyncMock)
    async def test_skips_already_sent_reminders(
        self,
        mock_reminder,
        db_session: AsyncSession,
        owner: User,
    ):
        session = await _make_session(db_session, owner, overdue=False)
        reminder = SessionReminder(
            session_id=session.id,
            fire_at=datetime.now(UTC) - timedelta(minutes=5),
            minutes_before=15,
            sent_at=datetime.now(UTC) - timedelta(minutes=4),
        )
        db_session.add(reminder)
        await db_session.commit()

        count = await process_pending_reminders(db_session)

        assert count == 0
        mock_reminder.assert_not_awaited()


@pytest.mark.asyncio
class TestScheduleRemindersForSession:
    async def test_creates_reminder_rows(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _make_session(db_session, owner, overdue=False)
        deadline = datetime.now(UTC) + timedelta(hours=2)

        count = await schedule_reminders_for_session(
            db_session, session.id, deadline
        )

        # Only the at-deadline rung (feeds the "time's up" SMS) — every
        # reminder PUSH is client-scheduled now (owner decision 2026-07-18).
        assert count == 1
