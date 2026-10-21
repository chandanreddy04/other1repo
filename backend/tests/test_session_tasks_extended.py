"""Extended session_tasks coverage — branches not hit by test_session_tasks.py."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus, SessionType
from app.services.session_tasks import (
    process_missed_session,
    process_overdue,
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
class TestProcessOverdueExtended:
    async def test_process_overdue_nonexistent_session(self, db_session: AsyncSession):
        result = await process_overdue(db_session, str(uuid4()))
        assert result["alerts_sent"] is False

    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_process_overdue_sos_type(
        self, mock_push_cls, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = AsyncMock(
            return_value=MagicMock(success=True, message_id="SM_SOS", provider=None)
        )
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await create_test_user(
            db_session, phone_number="+14155580100", full_name="Alice"
        )
        contact = await create_test_user(
            db_session, phone_number="+14155580101", full_name="Bob"
        )
        await _create_circle_member(db_session, owner, contact)

        session = await _create_session(
            db_session,
            owner,
            hours_offset=-1,
            session_type=SessionType.SOS.value,
        )

        result = await process_overdue(db_session, str(session.id))
        assert result["alerts_sent"] is True

        alerts = (
            await db_session.execute(
                select(Alert).where(Alert.session_id == session.id)
            )
        ).scalars().all()
        assert any(a.alert_type == AlertType.PANIC.value for a in alerts)


@pytest.mark.asyncio
class TestProcessMissedSession:
    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_process_missed_sends_to_unalerted_members(
        self, mock_push_cls, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = AsyncMock(
            return_value=MagicMock(success=True, message_id="SM_MISS", provider=None)
        )
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await create_test_user(
            db_session, phone_number="+14155580200", full_name="Missed Owner"
        )
        contact = await create_test_user(
            db_session, phone_number="+14155580201", full_name="Missed Contact"
        )
        await _create_circle_member(db_session, owner, contact)

        session = await _create_session(
            db_session, owner, hours_offset=-1, status=SessionStatus.MISSED.value
        )

        result = await process_missed_session(db_session, session.id)
        assert result["alerts_sent"] is True

    async def test_process_missed_nonexistent_session(self, db_session: AsyncSession):
        result = await process_missed_session(db_session, uuid4())
        assert result["alerts_sent"] is False

    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_process_missed_no_circle(
        self, mock_push_cls, mock_sms, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155580210"
        )
        session = await _create_session(
            db_session, owner, hours_offset=-1, status=SessionStatus.MISSED.value
        )
        result = await process_missed_session(db_session, session.id)
        assert result["alerts_sent"] is False
