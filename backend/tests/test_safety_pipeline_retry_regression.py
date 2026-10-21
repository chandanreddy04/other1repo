"""Regression test for C5: partial alert-dispatch failure must not get stuck.

Previously process_overdue only promoted MISSED->ALERTED when *every* member
was reached (all_dispatched). A partial failure (some reached, one failed)
left the session stuck MISSED forever, and the missed-retry pass skipped
members that already had an alert row — so the failed alert was never retried.

Now any reached member promotes the session to ALERTED, and the failed member's
delivery stays FAILED (retried with backoff by the outbox reconciler). A *total*
failure still stays MISSED until a member is reached (covered elsewhere).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
)
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.services.session_tasks import process_overdue
from app.services.sms import SMSResult
from tests.helpers import create_test_user


async def _member(db: AsyncSession, owner: User, phone: str) -> CircleOfTrustMember:
    contact = await create_test_user(db, phone_number=phone, full_name="C")
    m = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=contact.phone_number_id,
        nickname=contact.full_name,
        status=ContactStatus.ACTIVE.value,
    )
    db.add(m)
    await db.commit()
    return m


@pytest.mark.asyncio
@patch(
    "app.services.notification_outbox.ExpoPushNotificationService.send_notification",
    new_callable=AsyncMock,
)
@patch(
    "app.services.notification_outbox.sms_opt_out.gated_send_sms", new_callable=AsyncMock
)
async def test_partial_failure_promotes_to_alerted(
    mock_sms, mock_push, db_session: AsyncSession
):
    owner = await create_test_user(db_session, phone_number="+14155562001")
    await _member(db_session, owner, "+14155562002")
    await _member(db_session, owner, "+14155562003")

    session = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        status=SessionStatus.ACTIVE.value,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        location_sharing_enabled=False,
    )
    db_session.add(session)
    await db_session.commit()

    # Push off (no tokens); one member's SMS succeeds, the other fails.
    # Phone-aware so it's robust to the owner's own session-expired SMS also
    # flowing through the reconciler (its ordering is not guaranteed).
    mock_push.return_value = {"ok_tokens": [], "dead_tokens": []}

    async def _sms(db, phone, body, *args, **kwargs):
        if phone.endswith("2003"):
            return SMSResult(success=False, error="carrier down")
        return SMSResult(success=True, message_id="m1")

    mock_sms.side_effect = _sms

    await process_overdue(db_session, session.id)

    await db_session.refresh(session)
    # Reached at least one member -> promoted so the failed one can be retried.
    assert session.status == SessionStatus.ALERTED.value

    alerts = (
        await db_session.execute(select(Alert).where(Alert.session_id == session.id))
    ).scalars().all()
    assert len(alerts) == 2

    # One member's SMS reached (SENT), the other failed (retryable — FAILED, not
    # dropped; the reconciler backs off and retries it).
    sms_statuses = {
        d.status
        for d in (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.session_id == session.id,
                    NotificationDelivery.channel == DeliveryChannel.SMS,
                )
            )
        )
        .scalars()
        .all()
    }
    assert DeliveryStatus.SENT in sms_statuses
    assert DeliveryStatus.FAILED in sms_statuses
