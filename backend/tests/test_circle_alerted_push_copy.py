"""The owner's circle_alerted push carries the copy constants, not drift.

derive_session_promotions used to build this DeliveryDraft with no title and
the TITLE constant's text hardcoded as the body — losing the actionable
"Mark yourself safe when you can." entirely. Pin the draft to the constants
(notification_constants.py is the single source of truth for notification
copy) and pin the data payload the mobile routing contract keys on.

Related: app/services/notification_outbox.py::derive_session_promotions,
app/services/notification_constants.py.
"""

import uuid
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
from app.models.session import Session, SessionStatus
from app.services.notification_constants import (
    CIRCLE_ALERTED_BODY,
    CIRCLE_ALERTED_TITLE,
)
from app.services.notification_outbox import derive_session_promotions
from tests.helpers import create_test_user

_PHONE = iter(f"+141555960{n:02d}" for n in range(1, 99))


async def _missed_session_with_reached_alert(
    db: AsyncSession,
) -> Session:
    owner = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Olive Owner"
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=SessionStatus.MISSED.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    db.add(
        NotificationDelivery(
            dedupe_key=str(uuid.uuid4()),
            kind=NotificationKind.CIRCLE_ALERT,
            channel=DeliveryChannel.SMS,
            next_attempt_at=datetime.now(UTC),
            body="alert",
            status=DeliveryStatus.SENT,
            session_id=session.id,
            recipient_phone_id=owner.phone_number_id,
        )
    )
    await db.commit()
    return session


async def _circle_alerted_row(
    db: AsyncSession, session_id: uuid.UUID
) -> NotificationDelivery:
    result = await db.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.session_id == session_id,
            NotificationDelivery.kind == NotificationKind.CIRCLE_ALERTED,
        )
    )
    return result.scalar_one()


@pytest.mark.asyncio
class TestCircleAlertedPushCopy:
    async def test_promotion_draft_uses_the_copy_constants(
        self, db_session: AsyncSession
    ):
        session = await _missed_session_with_reached_alert(db_session)

        await derive_session_promotions(db_session)

        row = await _circle_alerted_row(db_session, session.id)
        assert row.title == CIRCLE_ALERTED_TITLE
        assert row.body == CIRCLE_ALERTED_BODY

    async def test_promotion_data_payload_unchanged(
        self, db_session: AsyncSession
    ):
        """The mobile routing contract keys on this payload — copy fixes must
        never touch it."""
        session = await _missed_session_with_reached_alert(db_session)

        await derive_session_promotions(db_session)

        row = await _circle_alerted_row(db_session, session.id)
        assert row.data == {
            "type": "circle_alerted",
            "session_id": str(session.id),
        }
