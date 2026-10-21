"""Regression pin for O7: a delivered circle_alert SMS must never produce a
false "contact unreachable" escalation for an app-account member who simply
has no push token.

Before commit a81e84c, `_enqueue_circle_alerts` also created a PUSH row for
every circle member with an app account (`contact_user`), alongside the SMS
row. A member who never granted push permission (or hadn't opened the app
since a reinstall) has `expo_push_token=None`, so that PUSH row was refused
immediately with "no push token" (`notification_outbox._dispatch_push`, via
`_resolve_push_token`). `send_due_deliveries` escalates on ANY REFUSED
circle-directed row regardless of channel, so the owner got a
"We couldn't reach {who}" push/SMS even though the member's SMS had already
been accepted. `process_overdue` runs `send_due_deliveries` inline, so the
false escalation appeared on the very first dispatch.

a81e84c dropped the PUSH branch from `_enqueue_circle_alerts` entirely —
Circle members are SMS-only now (`.claude/rules/domain-sessions-alerts.md`,
`tests/test_circle_alerts_sms_only.py`) — so a missing push token can no
longer produce a spurious PUSH row to refuse. This module pins that: a
delivered SMS produces zero PUSH rows for CIRCLE_ALERT and zero
`contact_unreachable` escalations, while a genuinely refused SMS (opted out)
still escalates — proving the fix is about the extra PUSH row, not about
escalation being disabled altogether.

Related: app/services/session_tasks.py (_enqueue_circle_alerts),
app/services/notification_outbox.py (send_due_deliveries, expire_and_escalate,
is_circle_unreachable), tests/test_circle_alerts_sms_only.py,
tests/test_outbox_escalation.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.services import notification_outbox as outbox
from app.services.notification_policy import POLICIES
from app.services.session_tasks import process_overdue
from app.services.sms import SMSResult
from tests.helpers import create_test_user

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


async def _count_unreachable(db: AsyncSession, owner_id) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.kind == NotificationKind.CONTACT_UNREACHABLE,
            NotificationDelivery.recipient_user_id == owner_id,
        )
    )


async def _count_circle_alert_push_rows(db: AsyncSession, session_id) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(
            NotificationDelivery.session_id == session_id,
            NotificationDelivery.kind == NotificationKind.CIRCLE_ALERT,
            NotificationDelivery.channel == DeliveryChannel.PUSH,
        )
    )


async def _circle_alert_sms_rows(
    db: AsyncSession, session_id
) -> list[NotificationDelivery]:
    return list(
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.session_id == session_id,
                    NotificationDelivery.kind == NotificationKind.CIRCLE_ALERT,
                    NotificationDelivery.channel == DeliveryChannel.SMS,
                )
            )
        )
        .scalars()
        .all()
    )


async def _assert_o7_precondition(db: AsyncSession, owner: User) -> None:
    """Pin the trigger shape so this test can't silently stop exercising it:
    the circle row resolves `contact_user` (the pre-a81e84c PUSH-row branch
    key) and that account has no push token."""
    row = await db.scalar(
        select(CircleOfTrustMember).where(CircleOfTrustMember.user_id == owner.id)
    )
    assert row is not None and row.contact_user is not None
    assert row.contact_user.expo_push_token is None


async def _owner(db: AsyncSession, phone: str) -> User:
    return await create_test_user(
        db,
        phone_number=phone,
        full_name="Ona Owner",
        expo_push_token="ExponentPushToken[owner]",
    )


async def _app_member_without_push_token(
    db: AsyncSession, owner: User, phone: str
) -> User:
    """A circle member with an app account (`contact_user` is set) but no
    push token registered — the O7 trigger condition."""
    contact = await create_test_user(
        db,
        phone_number=phone,
        full_name="Amy AppMember",
        expo_push_token=None,
    )
    db.add(
        CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=contact.phone_number_id,
            nickname=contact.full_name,
            status=ContactStatus.ACTIVE.value,
        )
    )
    await db.commit()
    return contact


def _sos_session(owner: User) -> Session:
    return Session(
        user_id=owner.id,
        session_type=SessionType.SOS.value,
        expected_return_time=NOW,
        status=SessionStatus.ACTIVE.value,
    )


@pytest.mark.asyncio
class TestUnreachableNotFiredWhenSmsDelivered:
    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_no_unreachable_and_no_push_row_when_member_sms_delivered(
        self, mock_push_cls, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = AsyncMock(
            return_value=SMSResult(success=True, message_id="SM1", provider=None)
        )
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await _owner(db_session, "+14155598001")
        member = await _app_member_without_push_token(db_session, owner, "+14155598002")
        await _assert_o7_precondition(db_session, owner)

        session = _sos_session(owner)
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        result = await process_overdue(db_session, str(session.id))
        assert result["alerts_sent"] is True

        # The member really did get the SMS (accepted, not silently skipped),
        # and that promoted the session MISSED → ALERTED.
        sent_to = [c.args[1] for c in mock_sms.gated_send_sms.await_args_list]
        assert member.phone_number in sent_to
        (sms_row,) = await _circle_alert_sms_rows(db_session, session.id)
        assert sms_row.status == DeliveryStatus.SENT
        assert sms_row.recipient_phone_id == member.phone_number_id
        await db_session.refresh(session)
        assert session.status == SessionStatus.ALERTED.value

        # The inline dispatch escalated nothing (pre-a81e84c it did, here).
        assert await _count_unreachable(db_session, owner.id) == 0

        # The member's SMS was accepted — no PUSH row was ever created for a
        # CIRCLE_ALERT (the O7 bug's extra row, keyed off contact_user, is gone).
        assert await _count_circle_alert_push_rows(db_session, session.id) == 0

        # Expire past the CIRCLE_ALERT TTL — a SENT SMS row is excluded from
        # expiry (`_EXPIRABLE_STATUSES`), so this must not escalate either.
        ttl = POLICIES[NotificationKind.CIRCLE_ALERT].expires_after
        assert ttl is not None
        far_future = datetime.now(UTC) + ttl + timedelta(hours=1)
        await outbox.expire_and_escalate(db_session, now=far_future)

        assert await _count_unreachable(db_session, owner.id) == 0
        await db_session.refresh(sms_row)
        assert sms_row.status == DeliveryStatus.SENT

        await db_session.refresh(session)
        assert await outbox.is_circle_unreachable(db_session, session) is False

    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_member_sms_refused_still_escalates(
        self, mock_push_cls, mock_sms, db_session: AsyncSession
    ):
        """Distinguishing case: the fix isn't "escalation never fires" — a
        genuinely undeliverable SMS (opted out) still produces a
        contact_unreachable escalation for the owner."""
        mock_sms.gated_send_sms = AsyncMock(
            return_value=SMSResult(success=False, error="opted_out")
        )
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await _owner(db_session, "+14155598003")
        member = await _app_member_without_push_token(db_session, owner, "+14155598004")
        await _assert_o7_precondition(db_session, owner)

        session = _sos_session(owner)
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        result = await process_overdue(db_session, str(session.id))
        assert result["alerts_sent"] is False

        assert await _count_circle_alert_push_rows(db_session, session.id) == 0
        # The escalation comes from the member's opted-out SMS row, not a PUSH.
        (sms_row,) = await _circle_alert_sms_rows(db_session, session.id)
        assert sms_row.status == DeliveryStatus.REFUSED
        assert sms_row.last_error == "opted_out"
        assert sms_row.recipient_phone_id == member.phone_number_id
        # One contact_unreachable per owner channel (deduped per member).
        assert await _count_unreachable(db_session, owner.id) == len(
            POLICIES[NotificationKind.CONTACT_UNREACHABLE].channels
        )

        await db_session.refresh(session)
        assert await outbox.is_circle_unreachable(db_session, session) is True
