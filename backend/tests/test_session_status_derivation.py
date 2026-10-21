"""derive_session_promotions: MISSED → ALERTED once a circle_alert is reached,
and the owner's circle_alerted push is enqueued. An unreached session stays
MISSED (no dead zone — its deliveries keep retrying).

Related: app/services/notification_outbox.py (derive_session_promotions).
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification_delivery import DeliveryDraft
from app.crud.notification_delivery import crud_notification_delivery as crud
from app.models.notification_delivery import (
    DeliveryChannel,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus
from app.services import notification_outbox as outbox
from tests.helpers import create_test_user

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


async def _missed_session(db, user) -> Session:
    s = Session(
        user_id=user.id,
        expected_return_time=NOW,
        status=SessionStatus.MISSED.value,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _circle_alert(db, *, key, user, session, sent: bool):
    await crud.enqueue(
        db,
        rows=[
            DeliveryDraft(
                dedupe_key=key,
                kind=NotificationKind.CIRCLE_ALERT,
                # Circle members are SMS-only (owner decision).
                channel=DeliveryChannel.SMS,
                body="hi",
                next_attempt_at=NOW,
                recipient_phone_id=user.phone_number_id,
                session_id=session.id,
            )
        ],
    )
    if sent:
        [d] = await crud.get_due(db, now=NOW)
        await crud.mark_sent(
            db, delivery=d, provider="twilio", provider_message_id=key, now=NOW
        )


async def _count_circle_alerted(db, owner_id) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.kind == NotificationKind.CIRCLE_ALERTED,
            NotificationDelivery.recipient_user_id == owner_id,
        )
    )


@pytest.mark.asyncio
class TestDerivePromotions:
    async def test_reached_session_promotes_and_enqueues_owner_push(
        self, db_session: AsyncSession
    ):
        u = await create_test_user(db_session, phone_number="+14155594001")
        s = await _missed_session(db_session, u)
        await _circle_alert(db_session, key="ca1", user=u, session=s, sent=True)

        result = await outbox.derive_session_promotions(db_session, now=NOW)
        assert result["promoted"] == 1
        await db_session.refresh(s)
        assert s.status == SessionStatus.ALERTED.value
        assert await _count_circle_alerted(db_session, u.id) == 1

    async def test_unreached_session_stays_missed(
        self, db_session: AsyncSession
    ):
        u = await create_test_user(db_session, phone_number="+14155594002")
        s = await _missed_session(db_session, u)
        await _circle_alert(db_session, key="ca2", user=u, session=s, sent=False)

        result = await outbox.derive_session_promotions(db_session, now=NOW)
        assert result["promoted"] == 0
        await db_session.refresh(s)
        assert s.status == SessionStatus.MISSED.value

    async def test_idempotent_second_run_does_not_repromote(
        self, db_session: AsyncSession
    ):
        u = await create_test_user(db_session, phone_number="+14155594003")
        s = await _missed_session(db_session, u)
        await _circle_alert(db_session, key="ca3", user=u, session=s, sent=True)

        await outbox.derive_session_promotions(db_session, now=NOW)
        # Already ALERTED → mark_as_alerted returns None → no second promotion.
        result = await outbox.derive_session_promotions(db_session, now=NOW)
        assert result["promoted"] == 0
        assert await _count_circle_alerted(db_session, u.id) == 1
