"""notification_deliveries model: enum round-trip, idempotency (dedupe_key),
and the recipient / push check constraints.

Related: app/models/notification_delivery.py.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from tests.helpers import create_test_user


def _delivery(**overrides) -> NotificationDelivery:
    base = {
        "dedupe_key": str(uuid.uuid4()),
        "kind": NotificationKind.CIRCLE_ALERT,
        "channel": DeliveryChannel.SMS,
        "next_attempt_at": datetime.now(UTC),
        "body": "hi",
    }
    base.update(overrides)
    return NotificationDelivery(**base)


@pytest.mark.asyncio
class TestNotificationDeliveryModel:
    async def test_round_trip_defaults_and_enums(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155590001")
        d = _delivery(
            channel=DeliveryChannel.PUSH,
            recipient_user_id=user.id,
            kind=NotificationKind.CIRCLE_ALERTED,
        )
        db_session.add(d)
        await db_session.commit()
        await db_session.refresh(d)
        assert d.status == DeliveryStatus.PENDING
        assert d.attempt_count == 0
        assert d.kind == NotificationKind.CIRCLE_ALERTED
        assert d.channel == DeliveryChannel.PUSH

    async def test_dedupe_key_is_unique(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155590002")
        db_session.add(_delivery(dedupe_key="dup", recipient_user_id=user.id))
        await db_session.commit()
        db_session.add(_delivery(dedupe_key="dup", recipient_user_id=user.id))
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_rejects_no_recipient(self, db_session: AsyncSession):
        db_session.add(_delivery())  # neither user nor phone
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_rejects_both_recipients(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155590003")
        db_session.add(
            _delivery(
                recipient_user_id=user.id,
                recipient_phone_id=user.phone_number_id,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()

    async def test_push_requires_a_user_recipient(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155590004")
        db_session.add(
            _delivery(
                channel=DeliveryChannel.PUSH,
                recipient_phone_id=user.phone_number_id,
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.commit()
