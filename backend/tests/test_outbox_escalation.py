"""Exhausting/refusing a circle_alert delivery escalates to the owner exactly
once (contact_unreachable, push + SMS), idempotent via the dedupe key.

Circle members are SMS-only (owner decision) — CIRCLE_ALERT no longer has a
push channel, so escalation is driven by a refused/exhausted SMS row.

Related: app/services/notification_outbox.py (_escalate_unreachable).
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
from app.models.session import Session
from app.services import notification_outbox as outbox
from app.services.sms import SMSResult
from tests.helpers import create_test_user

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


async def _count_unreachable(db, owner_id) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.kind == NotificationKind.CONTACT_UNREACHABLE,
            NotificationDelivery.recipient_user_id == owner_id,
        )
    )


@pytest.mark.asyncio
class TestEscalation:
    async def test_refused_circle_alert_escalates_once(
        self, db_session: AsyncSession, monkeypatch
    ):
        owner = await create_test_user(db_session, phone_number="+14155593001")
        member = await create_test_user(db_session, phone_number="+14155593002")
        session = Session(
            user_id=owner.id, expected_return_time=NOW, status="missed"
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        await crud.enqueue(
            db_session,
            rows=[
                DeliveryDraft(
                    dedupe_key="ca",
                    kind=NotificationKind.CIRCLE_ALERT,
                    channel=DeliveryChannel.SMS,
                    body="hi",
                    next_attempt_at=NOW,
                    recipient_phone_id=member.phone_number_id,
                    session_id=session.id,
                )
            ],
        )

        async def fake_sms(db, phone, body, **k):
            return SMSResult(success=False, error="opted_out")

        monkeypatch.setattr(outbox.sms_opt_out, "gated_send_sms", fake_sms)

        await outbox.send_due_deliveries(db_session, now=NOW)
        # CONTACT_UNREACHABLE policy = push + sms → 2 rows to the owner.
        assert await _count_unreachable(db_session, owner.id) == 2

        # Re-escalating the same (session, member) is a dedupe no-op.
        [refused] = list(
            (
                await db_session.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.dedupe_key == "ca"
                    )
                )
            )
            .scalars()
            .all()
        )
        await outbox._escalate_unreachable(db_session, refused, NOW)
        assert await _count_unreachable(db_session, owner.id) == 2
