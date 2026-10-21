"""Regression for C3: SMS-only circle contacts' alert failures must be tracked.

Previously an Alert row was only created for app-account contacts
(sent_to_user_id was NOT NULL), so a failed SMS to a phone-only contact (the
common case) left no record — never retried, never counted, and the session
still promoted to ALERTED. Now phone-only contacts get an Alert keyed on
sent_to_phone_id, so their failures are tracked + retryable.

Related: app/models/alert.py, app/services/session_tasks.py, migration 8ce884503ae7.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.models.alert import Alert
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
)
from app.models.session import Session, SessionStatus, SessionType
from app.services.sms import SMSResult
from tests.helpers import create_test_user


@pytest.mark.asyncio
@patch(
    "app.services.notification_outbox.ExpoPushNotificationService.send_notification",
    new_callable=AsyncMock,
)
@patch(
    "app.services.notification_outbox.sms_opt_out.gated_send_sms", new_callable=AsyncMock
)
async def test_phone_only_contact_failure_is_tracked(
    mock_sms, mock_push, db_session: AsyncSession
):
    from app.services.session_tasks import process_overdue

    owner = await create_test_user(db_session, phone_number="+14155564001")
    phone, _ = await crud_phone_number.get_or_create(db_session, number="+14155564002")
    member = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=phone.id,
        nickname="Mom",
        status=ContactStatus.ACTIVE.value,
    )
    db_session.add(member)
    session = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        status=SessionStatus.ACTIVE.value,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        location_sharing_enabled=False,
    )
    db_session.add(session)
    await db_session.commit()

    mock_push.return_value = {"ok_tokens": [], "dead_tokens": []}
    mock_sms.return_value = SMSResult(success=False, error="carrier down")

    await process_overdue(db_session, session.id)

    alerts = (
        await db_session.execute(select(Alert).where(Alert.session_id == session.id))
    ).scalars().all()
    # Previously: zero alerts (silently dropped). Now: one phone-keyed alert whose
    # failed SMS is tracked as a retryable delivery.
    assert len(alerts) == 1
    assert alerts[0].sent_to_phone_id == phone.id
    assert alerts[0].sent_to_user_id is None

    delivery = (
        await db_session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.alert_id == alerts[0].id
            )
        )
    ).scalar_one()
    assert delivery.channel == DeliveryChannel.SMS
    assert delivery.status == DeliveryStatus.FAILED
