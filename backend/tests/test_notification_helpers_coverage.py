"""Full coverage for notification_helpers.py.

Owner/circle lifecycle broadcasts now enqueue notification_deliveries rows
(the reconciler dispatches + retries them) rather than fire-and-forget pushes,
so those tests assert enqueued rows, not mocked send calls.
"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.services.notification_helpers import (
    send_all_clear_to_circle,
    send_data_deleted_notification,
    send_session_expired_notification,
)
from tests.helpers import create_test_user


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await create_test_user(
        db_session,
        phone_number="+14155551200",
        full_name="Owner O",
        expo_push_token="ExponentPushToken[owner]",
    )


async def _missed_session(db: AsyncSession, owner: User) -> Session:
    from datetime import UTC, datetime, timedelta

    s = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=5),
        status=SessionStatus.MISSED.value,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _member_list(db: AsyncSession, owner: User):
    from app.crud import crud_circle_of_trust

    return await crud_circle_of_trust.get_user_contacts(
        db, user_id=owner.id, status=ContactStatus.ACTIVE
    )


async def _rows(db: AsyncSession, session_id, kind) -> list[NotificationDelivery]:
    return list(
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
class TestSessionExpiredNotification:
    async def test_enqueues_owner_push_and_sms(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _missed_session(db_session, owner)
        n = await send_session_expired_notification(db_session, owner, session)
        assert n == 2
        rows = await _rows(
            db_session, session.id, NotificationKind.SESSION_EXPIRED_OWNER
        )
        assert {r.channel for r in rows} == {
            DeliveryChannel.PUSH,
            DeliveryChannel.SMS,
        }
        assert all(r.status == DeliveryStatus.PENDING for r in rows)

    async def test_rides_caller_transaction_without_committing(
        self, db_session: AsyncSession, owner: User
    ):
        """Enqueue-only: the rows exist on the caller's uncommitted transaction
        (process_overdue commits them alongside the circle alerts)."""
        session = await _missed_session(db_session, owner)
        await send_session_expired_notification(db_session, owner, session)
        # visible in-session before any commit
        count = await db_session.scalar(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(
                NotificationDelivery.kind
                == NotificationKind.SESSION_EXPIRED_OWNER
            )
        )
        assert count == 2

    async def test_idempotent_on_dedupe(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _missed_session(db_session, owner)
        await send_session_expired_notification(db_session, owner, session)
        n2 = await send_session_expired_notification(db_session, owner, session)
        assert n2 == 0  # dedupe_key collision → nothing new
        rows = await _rows(
            db_session, session.id, NotificationKind.SESSION_EXPIRED_OWNER
        )
        assert len(rows) == 2

    async def test_data_deleted_enqueues_owner_push(
        self, db_session: AsyncSession, owner: User
    ):
        session = await _missed_session(db_session, owner)
        n = await send_data_deleted_notification(db_session, owner, session)
        assert n == 1
        rows = await _rows(db_session, session.id, NotificationKind.DATA_DELETED)
        assert len(rows) == 1
        assert rows[0].channel == DeliveryChannel.PUSH


@pytest.mark.asyncio
class TestSendAllClearToCircle:
    @patch("app.services.notification_outbox.sms_opt_out.gated_send_sms", new_callable=AsyncMock)
    @patch("app.services.notification_outbox.ExpoPushNotificationService.send_notification", new_callable=AsyncMock)
    async def test_enqueues_all_clear_for_members(
        self, mock_push, mock_sms, db_session: AsyncSession, owner: User
    ):
        from app.services.sms import SMSProvider, SMSResult

        mock_push.return_value = {
            "ok_tokens": [],
            "dead_tokens": [],
            "ticket_ids": {},
        }
        mock_sms.return_value = SMSResult(
            success=True, message_id="SM1", provider=SMSProvider.TWILIO
        )
        contact = await create_test_user(
            db_session,
            phone_number="+14155551201",
            full_name="Bea B",
            expo_push_token="ExponentPushToken[bea]",
        )
        session = await _missed_session(db_session, owner)
        db_session.add(
            CircleOfTrustMember(
                user_id=owner.id,
                contact_phone_number_id=contact.phone_number_id,
                nickname=contact.full_name,
                status=ContactStatus.ACTIVE.value,
            )
        )
        await db_session.commit()
        members = await _member_list(db_session, owner)

        n = await send_all_clear_to_circle(db_session, members, owner, session)
        # Circle members are SMS-only (owner decision) — no push, even for
        # an app-account member.
        assert n == 1
        rows = await _rows(db_session, session.id, NotificationKind.ALL_CLEAR)
        assert {r.channel for r in rows} == {DeliveryChannel.SMS}
