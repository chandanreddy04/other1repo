"""Tests for session task business logic (services/session_tasks.py)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus, SessionType
from app.services.session_tasks import (
    cleanup_expired_data,
    process_overdue,
    send_owner_reminder,
)
from tests.helpers import create_test_user


async def _create_session(
    db: AsyncSession,
    user,
    *,
    status: str = SessionStatus.ACTIVE.value,
    session_type: str = SessionType.CHECKIN.value,
    hours_offset: int = 2,
    **kwargs,
) -> Session:
    session = Session(
        user_id=user.id,
        session_type=session_type,
        expected_return_time=datetime.now(UTC) + timedelta(hours=hours_offset),
        status=status,
        **kwargs,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _create_circle_member(
    db: AsyncSession,
    owner,
    contact,
    *,
    status: str = ContactStatus.ACTIVE.value,
) -> CircleOfTrustMember:
    member = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=contact.phone_number_id,
        nickname=contact.full_name,
        status=status,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest.mark.asyncio
class TestProcessOverdue:
    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_claims_and_creates_alerts(
        self,
        mock_push_cls,
        mock_sms,
        db_session: AsyncSession,
    ):
        mock_sms.gated_send_sms = AsyncMock(
            return_value=MagicMock(success=True, message_id="SM123", provider=None)
        )
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await create_test_user(
            db_session, phone_number="+14155570100", full_name="Alice"
        )
        contact = await create_test_user(
            db_session, phone_number="+14155570101", full_name="Bob"
        )
        await _create_circle_member(db_session, owner, contact)

        session = await _create_session(db_session, owner, hours_offset=-1)

        result = await process_overdue(db_session, str(session.id))

        assert result["alerts_sent"] is True

        await db_session.refresh(session)
        assert session.status == SessionStatus.ALERTED.value

    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_skips_non_active_session(
        self,
        mock_push_cls,
        mock_sms,
        db_session: AsyncSession,
    ):
        owner = await create_test_user(db_session, phone_number="+14155570102")
        session = await _create_session(
            db_session, owner, status=SessionStatus.COMPLETED.value
        )

        result = await process_overdue(db_session, str(session.id))
        assert result["alerts_sent"] is False

    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_no_circle_members(
        self,
        mock_push_cls,
        mock_sms,
        db_session: AsyncSession,
    ):
        owner = await create_test_user(db_session, phone_number="+14155570103")
        session = await _create_session(db_session, owner, hours_offset=-1)

        result = await process_overdue(db_session, str(session.id))
        assert result["alerts_sent"] is False

        await db_session.refresh(session)
        assert session.status == SessionStatus.MISSED.value

    # Patch the reconciler's provider bindings (it owns the actual send now).
    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_marks_alert_failed_when_all_delivery_fails(
        self,
        mock_push_cls,
        mock_sms,
        db_session: AsyncSession,
    ):
        mock_sms.gated_send_sms = AsyncMock(
            return_value=MagicMock(success=False, message_id=None, error="Failed")
        )
        mock_push_cls.send_notification = AsyncMock(side_effect=Exception("Push error"))

        owner = await create_test_user(
            db_session, phone_number="+14155570106", full_name="Alice"
        )
        contact = await create_test_user(
            db_session, phone_number="+14155570107", full_name="Bob"
        )
        await _create_circle_member(db_session, owner, contact)

        session = await _create_session(db_session, owner, hours_offset=-1)
        await process_overdue(db_session, str(session.id))

        result = await db_session.execute(
            select(Alert).where(
                Alert.session_id == session.id,
                Alert.sent_to_user_id == contact.id,
            )
        )
        alert = result.scalar_one()
        # All deliveries failed on the first attempt → each tracked as FAILED
        # (retryable); the reconciler backs off and retries. The alert isn't
        # marked FAILED until its deliveries exhaust.
        from app.models.notification_delivery import (
            DeliveryStatus,
            NotificationDelivery,
        )

        deliveries = (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.alert_id == alert.id
                )
            )
        ).scalars().all()
        assert deliveries
        # Nothing reached: SMS FAILED (retryable), push REFUSED (no token).
        assert all(
            d.status in (DeliveryStatus.FAILED, DeliveryStatus.REFUSED)
            for d in deliveries
        )


@pytest.mark.asyncio
class TestSendOwnerReminder:
    async def test_enqueues_reminder_for_active_session(
        self, db_session: AsyncSession
    ):
        from app.models.notification_delivery import (
            NotificationDelivery,
            NotificationKind,
        )

        owner = await create_test_user(
            db_session, phone_number="+14155570300", expo_push_token="ExponentPushToken[xxx]"
        )
        session = await _create_session(db_session, owner, hours_offset=1)

        # The at-deadline rung enqueues the owner_deadline SMS — the server's
        # only reminder channel now; every reminder PUSH is a client-scheduled
        # local notification (owner decision 2026-07-18, ladder coverage in
        # mobile/services/notifications.reminderLadder.test.ts).
        result = await send_owner_reminder(db_session, str(session.id), 0)
        assert result is True
        deliveries = (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.session_id == session.id,
                    NotificationDelivery.kind == NotificationKind.OWNER_DEADLINE,
                )
            )
        ).scalars().all()
        assert len(deliveries) == 1
        assert deliveries[0].recipient_user_id == owner.id

    async def test_skips_non_active_session(self, db_session: AsyncSession):
        owner = await create_test_user(db_session, phone_number="+14155570301")
        session = await _create_session(
            db_session, owner, status=SessionStatus.COMPLETED.value
        )

        result = await send_owner_reminder(db_session, str(session.id), 30)
        assert result is False


@pytest.mark.asyncio
class TestCleanupExpiredData:
    @patch("app.services.session_tasks.BlobStorageService")
    async def test_cleans_up_expired_session_data(
        self,
        mock_s3_cls,
        db_session: AsyncSession,
    ):
        mock_s3 = MagicMock()
        mock_s3.delete_file = AsyncMock(return_value=True)
        mock_s3_cls.return_value = mock_s3

        owner = await create_test_user(db_session, phone_number="+14155570400")
        await _create_session(
            db_session,
            owner,
            status=SessionStatus.COMPLETED.value,
            outfit_photo_url="https://madeithome-photos.s3.us-west-2.amazonaws.com/photos/photo.jpg",
        )
        result = await cleanup_expired_data(db_session)
        assert result["photos_deleted"] == 1
        mock_s3.delete_file.assert_called_once()

    @patch("app.services.session_tasks.BlobStorageService")
    async def test_skips_active_sessions(
        self,
        mock_s3_cls,
        db_session: AsyncSession,
    ):
        mock_s3_cls.return_value = MagicMock()

        owner = await create_test_user(db_session, phone_number="+14155570401")
        await _create_session(
            db_session,
            owner,
            status=SessionStatus.ACTIVE.value,
            outfit_photo_url="https://madeithome-photos.s3.us-west-2.amazonaws.com/photos/photo.jpg",
        )

        result = await cleanup_expired_data(db_session)
        assert result["photos_deleted"] == 0
        assert result["locations_deleted"] == 0
