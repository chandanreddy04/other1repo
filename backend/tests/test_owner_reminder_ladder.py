"""Owner reminder ladder + server-truth circle-alerted push.

Covers the 2026-07-02 flow-review decisions (docs/flow-review.md §4.3 C2,
3.4, §4.4): reminders at [30, 10, 0] minutes; the at-deadline reminder gets
distinct "time's up" copy plus an SMS fallback (reaches phones with
notifications denied/DND); grace is 5 minutes; and the owner gets a
`circle_alerted` push only when a circle member has ACTUALLY been reached
(MISSED → ALERTED promotion) — the mobile app must never claim "notified"
from the client clock.

Related: app/services/notification_helpers.py, app/services/session_tasks.py,
app/core/config.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus
from app.services.session_tasks import process_overdue
from tests.helpers import create_test_user


class TestReminderLadderConfig:
    def test_reminder_times_are_30_10_0(self):
        """[30, 10] pre-deadline + the at-deadline nudge (flow-review C2)."""
        assert settings.ALERT_REMINDER_TIMES == [30, 10, 0]

    def test_grace_period_is_five_minutes(self):
        """5-minute owner-nag window before the circle alert (§4.4.1)."""
        assert settings.GRACE_PERIOD_MINUTES == 5


@pytest.mark.asyncio
class TestCircleAlertedPush:
    async def test_owner_notified_on_missed_to_alerted_promotion(
        self, db_session: AsyncSession
    ):
        """process_overdue reaching ≥1 member → owner gets circle_alerted."""
        owner = await create_test_user(
            db_session, phone_number="+14155595003", full_name="Owner"
        )
        owner.expo_push_token = "ExponentPushToken[test-owner-alerted]"
        contact = await create_test_user(
            db_session, phone_number="+14155595004", full_name="Contact"
        )
        db_session.add(
            CircleOfTrustMember(
                user_id=owner.id,
                contact_phone_number_id=contact.phone_number_id,
                nickname=contact.full_name,
                status=ContactStatus.ACTIVE.value,
            )
        )
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        from app.models.notification_delivery import (
            NotificationDelivery,
            NotificationKind,
        )
        from app.services.sms import SMSResult

        with (
            patch(
                "app.services.notification_outbox.sms_opt_out.gated_send_sms",
                new_callable=AsyncMock,
                return_value=SMSResult(success=True, message_id="m"),
            ),
            patch(
                "app.services.notification_outbox.ExpoPushNotificationService.send_notification",
                new_callable=AsyncMock,
                return_value={"ok_tokens": [], "dead_tokens": [], "ticket_ids": {}},
            ),
        ):
            result = await process_overdue(db_session, session.id)

        assert result["alerts_sent"] is True
        await db_session.refresh(session)
        assert session.status == SessionStatus.ALERTED.value
        # The promotion enqueues the owner's server-truth "circle notified" push.
        circle_alerted = (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.kind == NotificationKind.CIRCLE_ALERTED,
                    NotificationDelivery.recipient_user_id == owner.id,
                )
            )
        ).scalars().all()
        assert len(circle_alerted) == 1
        assert circle_alerted[0].data.get("type") == "circle_alerted"
