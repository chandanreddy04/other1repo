"""A SENT push whose Expo receipt never arrives expires (feat brief O14/B).

`crud_notification_delivery.expire_overdue`'s docstring used to claim it
covered "a 'sent' push whose receipt never arrived," but `_EXPIRABLE_STATUSES`
never included SENT — so a push accepted by Expo but never confirmed
delivered stayed SENT forever. This module pins the fix: a SENT row on the
PUSH channel, of a receipt-tracked kind, older than `RECEIPT_WINDOW` with no
receipt, is reaped to EXHAUSTED with `last_error="no receipt"` when the
caller opts in via `push_receipt_kinds` (the production call site,
`notification_outbox.expire_and_escalate`, always passes `_RECEIPT_KINDS`).

Also pins: a SENT SMS is NEVER touched (Twilio may deliver hours later —
the delivery webhook is the source of truth), a row younger than the window
is untouched, a freshly-claimed row is skipped like the rest of
expire_overdue, and `poll_expo_receipts` followed by `expire_overdue` never
double-transitions the same row (poll only ever leaves a row it processed as
DELIVERED, REFUSED, or FAILED-with-backoff — never SENT with an old
`sent_at`).

Related: app/crud/notification_delivery.py (expire_overdue, RECEIPT_WINDOW),
app/services/notification_outbox.py (expire_and_escalate, poll_expo_receipts,
_RECEIPT_KINDS), docs/notifications.md (§1 expire_and_escalate row).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification_delivery import RECEIPT_WINDOW, DeliveryDraft
from app.crud.notification_delivery import (
    crud_notification_delivery as crud,
)
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationKind,
)
from app.services import notification_outbox as outbox
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)

# SESSION_EXPIRED_OWNER carries both PUSH and SMS (both receipt-tracked at
# the policy level, but only PUSH is ever polled/expired for a receipt) —
# using one kind for both channels below proves the gate is on `channel`,
# not just `kind`.
_KIND = NotificationKind.SESSION_EXPIRED_OWNER


def _draft(
    *,
    key: str,
    channel: DeliveryChannel,
    recipient_user_id=None,
    recipient_phone_id=None,
) -> DeliveryDraft:
    return DeliveryDraft(
        dedupe_key=key,
        kind=_KIND,
        channel=channel,
        body="b",
        next_attempt_at=NOW,
        recipient_user_id=recipient_user_id,
        recipient_phone_id=recipient_phone_id,
        expires_at=None,
    )


class TestSentPushExpiry:
    async def test_sent_push_older_than_window_with_no_receipt_expires(
        self, db_session: AsyncSession
    ) -> None:
        user = await create_test_user(db_session, phone_number="+14155599201")
        draft = _draft(key="push1", channel=DeliveryChannel.PUSH, recipient_user_id=user.id)
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="expo", provider_message_id="t1", now=NOW
        )
        await db_session.commit()

        old_enough = NOW + RECEIPT_WINDOW + timedelta(minutes=1)
        expired = await crud.expire_overdue(
            db_session, now=old_enough, push_receipt_kinds=[_KIND]
        )

        assert [e.dedupe_key for e in expired] == ["push1"]
        assert expired[0].status == DeliveryStatus.EXHAUSTED
        assert expired[0].last_error == "no receipt"

    async def test_sent_push_younger_than_window_is_untouched(
        self, db_session: AsyncSession
    ) -> None:
        user = await create_test_user(db_session, phone_number="+14155599202")
        draft = _draft(key="push2", channel=DeliveryChannel.PUSH, recipient_user_id=user.id)
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="expo", provider_message_id="t2", now=NOW
        )
        await db_session.commit()

        just_under = NOW + RECEIPT_WINDOW - timedelta(seconds=1)
        expired = await crud.expire_overdue(
            db_session, now=just_under, push_receipt_kinds=[_KIND]
        )

        assert expired == []
        await db_session.refresh(row)
        assert row.status == DeliveryStatus.SENT

    async def test_sent_sms_older_than_window_is_untouched(
        self, db_session: AsyncSession
    ) -> None:
        """Twilio can deliver hours later; the delivery webhook, not a
        timeout, is the source of truth for a SENT SMS."""
        user = await create_test_user(db_session, phone_number="+14155599203")
        draft = _draft(
            key="sms1", channel=DeliveryChannel.SMS, recipient_phone_id=user.phone_number_id
        )
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="twilio", provider_message_id="SM1", now=NOW
        )
        await db_session.commit()

        far_future = NOW + timedelta(days=3)
        expired = await crud.expire_overdue(
            db_session, now=far_future, push_receipt_kinds=[_KIND]
        )

        assert expired == []
        await db_session.refresh(row)
        assert row.status == DeliveryStatus.SENT

    async def test_no_push_receipt_kinds_passed_leaves_sent_push_untouched(
        self, db_session: AsyncSession
    ) -> None:
        """The default (no `push_receipt_kinds`) preserves the original
        PENDING/FAILED-only behaviour — a caller that doesn't opt in (as
        existing tests don't) never reaps a SENT push."""
        user = await create_test_user(db_session, phone_number="+14155599204")
        draft = _draft(key="push3", channel=DeliveryChannel.PUSH, recipient_user_id=user.id)
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="expo", provider_message_id="t3", now=NOW
        )
        await db_session.commit()

        far_future = NOW + timedelta(days=1)
        expired = await crud.expire_overdue(db_session, now=far_future)

        assert expired == []
        await db_session.refresh(row)
        assert row.status == DeliveryStatus.SENT

    async def test_freshly_claimed_row_is_untouched(
        self, db_session: AsyncSession
    ) -> None:
        """Respects a fresh claim the same way the PENDING/FAILED sweep
        does, even though nothing in normal flow claims a SENT row."""
        user = await create_test_user(db_session, phone_number="+14155599205")
        draft = _draft(key="push4", channel=DeliveryChannel.PUSH, recipient_user_id=user.id)
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="expo", provider_message_id="t4", now=NOW
        )
        old_enough = NOW + RECEIPT_WINDOW + timedelta(minutes=1)
        row.claimed_at = old_enough - timedelta(minutes=1)  # fresh relative to `old_enough`
        await db_session.commit()

        expired = await crud.expire_overdue(
            db_session, now=old_enough, push_receipt_kinds=[_KIND]
        )

        assert expired == []
        await db_session.refresh(row)
        assert row.status == DeliveryStatus.SENT

    async def test_poll_then_expire_never_double_transitions(
        self, db_session: AsyncSession
    ) -> None:
        """poll_expo_receipts moves a row out of SENT (to DELIVERED here);
        expire_overdue run right after must be a no-op for it."""
        user = await create_test_user(db_session, phone_number="+14155599206")
        draft = _draft(key="push5", channel=DeliveryChannel.PUSH, recipient_user_id=user.id)
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="expo", provider_message_id="t5", now=NOW
        )
        await db_session.commit()

        old_enough = NOW + RECEIPT_WINDOW + timedelta(minutes=1)
        with patch.object(
            outbox.ExpoPushNotificationService,
            "get_receipts",
            new=AsyncMock(
                return_value={"receipts": {"t5": {"ok": True, "dead": False}}}
            ),
        ):
            await outbox.poll_expo_receipts(db_session, now=old_enough)
        await db_session.refresh(row)
        assert row.status == DeliveryStatus.DELIVERED

        expired = await crud.expire_overdue(
            db_session, now=old_enough, push_receipt_kinds=[_KIND]
        )
        assert expired == []
        await db_session.refresh(row)
        assert row.status == DeliveryStatus.DELIVERED

    async def test_exactly_at_window_boundary_expires(
        self, db_session: AsyncSession
    ) -> None:
        """The boundary is inclusive: `sent_at` exactly RECEIPT_WINDOW old is
        reaped (the 1-second-under case is pinned above)."""
        user = await create_test_user(db_session, phone_number="+14155599207")
        draft = _draft(key="push6", channel=DeliveryChannel.PUSH, recipient_user_id=user.id)
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="expo", provider_message_id="t6", now=NOW
        )
        await db_session.commit()

        expired = await crud.expire_overdue(
            db_session, now=NOW + RECEIPT_WINDOW, push_receipt_kinds=[_KIND]
        )

        assert [e.dedupe_key for e in expired] == ["push6"]
        assert expired[0].status == DeliveryStatus.EXHAUSTED

    async def test_receipt_arriving_after_reap_is_ignored(
        self, db_session: AsyncSession
    ) -> None:
        """Receipt shows up at minute 31, after the minute-30 reap: the poll
        only selects SENT rows, so it never sees (or re-transitions) the
        EXHAUSTED row and never asks Expo about it."""
        user = await create_test_user(db_session, phone_number="+14155599208")
        draft = _draft(key="push7", channel=DeliveryChannel.PUSH, recipient_user_id=user.id)
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="expo", provider_message_id="t7", now=NOW
        )
        await db_session.commit()

        reaped = await crud.expire_overdue(
            db_session, now=NOW + RECEIPT_WINDOW, push_receipt_kinds=[_KIND]
        )
        await db_session.commit()
        assert [e.dedupe_key for e in reaped] == ["push7"]

        late = AsyncMock(return_value={"receipts": {"t7": {"ok": True, "dead": False}}})
        with patch.object(outbox.ExpoPushNotificationService, "get_receipts", new=late):
            counts = await outbox.poll_expo_receipts(
                db_session, now=NOW + RECEIPT_WINDOW + timedelta(minutes=1)
            )

        late.assert_not_awaited()
        assert counts["delivered"] == 0
        await db_session.refresh(row)
        assert row.status == DeliveryStatus.EXHAUSTED
        assert row.last_error == "no receipt"

    async def test_expire_and_escalate_reaps_sent_push_without_escalating(
        self, db_session: AsyncSession
    ) -> None:
        """The production call site passes the policy-derived receipt kinds,
        and a reaped SENT push goes through the same `escalate_on_exhausted`
        gate as any other exhausted row — no push kind escalates, so no
        `contact_unreachable` is enqueued."""
        user = await create_test_user(db_session, phone_number="+14155599209")
        draft = _draft(key="push8", channel=DeliveryChannel.PUSH, recipient_user_id=user.id)
        await crud.enqueue(db_session, rows=[draft])
        [row] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=row, provider="expo", provider_message_id="t8", now=NOW
        )
        await db_session.commit()

        with patch.object(
            outbox, "_escalate_unreachable", new=AsyncMock()
        ) as mock_escalate:
            counts = await outbox.expire_and_escalate(
                db_session, now=NOW + RECEIPT_WINDOW + timedelta(minutes=1)
            )

        assert counts["expired"] == 1
        mock_escalate.assert_not_awaited()
        await db_session.refresh(row)
        assert row.status == DeliveryStatus.EXHAUSTED
        assert row.last_error == "no receipt"
