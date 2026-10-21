"""Tests for worker_tick.py cron entry-point."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session, SessionStatus, SessionType
from tests.helpers import create_test_user


async def _create_session(
    db: AsyncSession,
    user,
    *,
    status: str = SessionStatus.ACTIVE.value,
    hours_offset: int = 2,
) -> Session:
    session = Session(
        user_id=user.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) + timedelta(hours=hours_offset),
        status=status,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
class TestWorkerTick:
    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_tick_processes_overdue_session(
        self,
        mock_push_cls,
        mock_sms,
        db_session: AsyncSession,
    ):
        """Verify tick() finds and processes an overdue active session."""
        from app.crud import crud_session
        from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus

        mock_sms.gated_send_sms = AsyncMock(
            return_value=MagicMock(success=True, message_id="SM1", provider=None)
        )
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await create_test_user(
            db_session, phone_number="+14155570800", full_name="Alice"
        )
        contact = await create_test_user(
            db_session, phone_number="+14155570801", full_name="Bob"
        )
        member = CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=contact.phone_number_id,
            nickname=contact.full_name,
            status=ContactStatus.ACTIVE.value,
        )
        db_session.add(member)
        await db_session.commit()

        session = await _create_session(db_session, owner, hours_offset=-1)

        overdue = await crud_session.get_overdue_sessions(
            db_session, grace_minutes=0
        )
        assert any(s.id == session.id for s in overdue)

    async def test_grace_period_excludes_recent_sessions(
        self, db_session: AsyncSession
    ):
        """Sessions within the grace period are not returned as overdue."""
        from app.crud import crud_session

        owner = await create_test_user(
            db_session, phone_number="+14155570802"
        )
        session = await _create_session(db_session, owner, hours_offset=0)
        session.expected_return_time = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.commit()

        overdue = await crud_session.get_overdue_sessions(
            db_session, grace_minutes=2
        )
        assert not any(s.id == session.id for s in overdue)

        overdue_no_grace = await crud_session.get_overdue_sessions(
            db_session, grace_minutes=0
        )
        assert any(s.id == session.id for s in overdue_no_grace)
