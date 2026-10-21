"""Every push is auditable via the notification outbox (owner decision).

Previously the two account-holder STOP pushes bypassed the outbox and called
`ExpoPushNotificationService.send_notification` directly — no delivery row,
no retry, no Expo receipt:

- `notification_helpers.send_account_holder_unsubscribed` (the STOP webhook,
  `data={"type": "account_holder_unsubscribed"}`)
- `notification_helpers.send_account_holder_subscription_cancelled` (the
  sweep in `sms_unsubscribe_tasks.py`, grace_days after STOP)

Both now enqueue `NotificationDelivery` rows (kinds
ACCOUNT_HOLDER_UNSUBSCRIBED and ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED) and
dispatch through the reconciler (`app.services.notification_outbox`), so this
file asserts outbox rows rather than direct provider calls — patch targets
follow `test_no_stale_dispatch_patches.py`'s rule (patch the reconciler, not
the enqueue-only helper module).

Related: app/services/notification_helpers.py, app/services/sms_unsubscribe_tasks.py,
         app/services/notification_outbox.py, app/services/notification_policy.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import crud_notification_delivery
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.services import sms_opt_out
from app.services.notification_helpers import (
    send_account_holder_subscription_cancelled,
    send_account_holder_unsubscribed,
)
from app.services.notification_policy import CIRCLE_DIRECTED_KINDS, POLICIES
from app.services.sms_unsubscribe_tasks import process_unhandled_sms_unsubscribes
from tests.helpers import create_test_subscription, create_test_user


def _expo_ok_for(*tokens: str) -> dict:
    return {
        "ok_tokens": list(tokens),
        "dead_tokens": [],
        "ticket_ids": {t: f"ticket-{t}" for t in tokens},
    }


async def _rows_for_kind(
    db: AsyncSession, kind: NotificationKind
) -> list[NotificationDelivery]:
    result = await db.execute(
        select(NotificationDelivery).where(NotificationDelivery.kind == kind)
    )
    return list(result.scalars().all())


def _enqueue_with_real_db_error(fail_user_ids: set):
    """A `crud_nd.enqueue` stand-in that raises a REAL database error (not a
    Python exception) for rows addressed to `fail_user_ids` — the statement
    aborts the open transaction exactly like a failed outbox insert would —
    and enqueues normally for everyone else."""
    real_enqueue = crud_notification_delivery.enqueue

    async def fake(db: AsyncSession, *, rows):
        if any(r.recipient_user_id in fail_user_ids for r in rows):
            await db.execute(text("SELECT 1/0"))
        return await real_enqueue(db, rows=rows)

    return fake


async def _backdate_opt_out(db: AsyncSession, phone: str, days: int) -> None:
    """Pretend the user texted STOP `days` ago."""
    from app.crud.phone_number import crud_phone_number

    pn, _ = await crud_phone_number.get_or_create(db, number=phone)
    pn.sms_opted_out_at = datetime.now(UTC) - timedelta(days=days)
    pn.sms_opt_out_source = "test"
    await db.commit()


class TestPolicyInvariants:
    def test_new_kinds_are_receipt_tracked(self):
        assert (
            POLICIES[NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED].track_expo_receipts
            is True
        )
        assert (
            POLICIES[
                NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED
            ].track_expo_receipts
            is True
        )

    def test_new_kinds_are_push_only(self):
        assert POLICIES[NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED].channels == (
            DeliveryChannel.PUSH,
        )
        assert POLICIES[
            NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED
        ].channels == (DeliveryChannel.PUSH,)

    def test_new_kinds_are_not_circle_directed(self):
        assert NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED not in CIRCLE_DIRECTED_KINDS
        assert (
            NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED
            not in CIRCLE_DIRECTED_KINDS
        )
        assert (
            POLICIES[NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED].escalate_on_exhausted
            is False
        )
        assert (
            POLICIES[
                NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED
            ].escalate_on_exhausted
            is False
        )


@pytest.mark.asyncio
class TestAccountHolderUnsubscribedOutbox:
    async def test_stop_enqueues_one_sent_push_row_with_existing_body(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session,
            phone_number="+14155570001",
            full_name="Uma User",
            expo_push_token="ExponentPushToken[uma]",
        )
        await sms_opt_out.record_opt_out(db_session, user.phone_number)
        await db_session.refresh(user)

        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(user.expo_push_token)
            )
            await send_account_holder_unsubscribed(db_session, user)

        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.channel == DeliveryChannel.PUSH
        assert row.recipient_user_id == user.id
        assert row.title == "You unsubscribed from Made It Home"
        assert row.body == (
            "Texts are off — including your sign-in codes and alerts about "
            "people whose Circle you're in. Tap to manage."
        )
        assert row.data == {"type": "account_holder_unsubscribed"}
        assert row.status == DeliveryStatus.SENT
        assert POLICIES[row.kind].track_expo_receipts is True

    async def test_no_push_token_gets_refused_row(self, db_session: AsyncSession):
        user = await create_test_user(
            db_session, phone_number="+14155570002", full_name="Nora NoToken"
        )
        await sms_opt_out.record_opt_out(db_session, user.phone_number)
        await db_session.refresh(user)

        await send_account_holder_unsubscribed(db_session, user)

        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED
        )
        assert len(rows) == 1
        assert rows[0].status == DeliveryStatus.REFUSED
        assert rows[0].last_error == "no push token"

    async def test_stop_start_stop_notifies_twice(self, db_session: AsyncSession):
        """A second STOP after an intervening START is a fresh opt-out
        timestamp, so it must notify again rather than deduping against
        the first STOP's row."""
        phone_str = "+14155570003"
        user = await create_test_user(
            db_session,
            phone_number=phone_str,
            full_name="Sasha StopStart",
            expo_push_token="ExponentPushToken[sasha]",
        )

        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(user.expo_push_token)
            )

            await sms_opt_out.record_opt_out(db_session, phone_str)
            await db_session.refresh(user)
            await send_account_holder_unsubscribed(db_session, user)

            await sms_opt_out.record_opt_in(db_session, phone_str)
            await sms_opt_out.record_opt_out(db_session, phone_str)
            await db_session.refresh(user)
            await send_account_holder_unsubscribed(db_session, user)

        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED
        )
        assert len(rows) == 2
        assert len({r.dedupe_key for r in rows}) == 2
        assert all(r.status == DeliveryStatus.SENT for r in rows)

    async def test_repeated_stop_while_opted_out_dedupes(
        self, db_session: AsyncSession
    ):
        """record_opt_out keeps the original timestamp on a repeated STOP,
        so the occurrence is unchanged and the second call is a no-op."""
        user = await create_test_user(
            db_session,
            phone_number="+14155570004",
            full_name="Rita Repeat",
            expo_push_token="ExponentPushToken[rita]",
        )
        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(user.expo_push_token)
            )
            await sms_opt_out.record_opt_out(db_session, user.phone_number)
            await db_session.refresh(user)
            await send_account_holder_unsubscribed(db_session, user)
            await sms_opt_out.record_opt_out(db_session, user.phone_number)
            await db_session.refresh(user)
            await send_account_holder_unsubscribed(db_session, user)

        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED
        )
        assert len(rows) == 1
        assert mock_push_cls.send_notification.await_count == 1

    async def test_dead_token_is_cleared_by_the_outbox(
        self, db_session: AsyncSession
    ):
        """The helper no longer clears dead tokens itself — the reconciler's
        `_dispatch_push` does, and records the row REFUSED."""
        user = await create_test_user(
            db_session,
            phone_number="+14155570005",
            full_name="Dana Dead",
            expo_push_token="ExponentPushToken[dana-dead]",
        )
        await sms_opt_out.record_opt_out(db_session, user.phone_number)
        await db_session.refresh(user)

        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value={
                    "ok_tokens": [],
                    "dead_tokens": ["ExponentPushToken[dana-dead]"],
                    "ticket_ids": {},
                }
            )
            await send_account_holder_unsubscribed(db_session, user)

        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED
        )
        assert len(rows) == 1
        assert rows[0].status == DeliveryStatus.REFUSED
        assert rows[0].last_error == "DeviceNotRegistered"
        await db_session.refresh(user)
        assert user.expo_push_token is None

    async def test_stop_webhook_survives_a_db_error_enqueueing_the_push(
        self, db_session: AsyncSession, client: AsyncClient
    ):
        """A real DB error in the outbox insert aborts the transaction. The
        webhook must still ack Twilio (200 — a non-2xx makes Twilio retry the
        STOP), keep the committed opt-out, and leave the session usable
        (rolled back, not stuck in a failed transaction)."""
        user = await create_test_user(
            db_session,
            phone_number="+14155570006",
            full_name="Ezra Error",
            expo_push_token="ExponentPushToken[ezra]",
        )

        with patch(
            "app.services.notification_outbox.crud_nd.enqueue",
            new=_enqueue_with_real_db_error({user.id}),
        ):
            response = await client.post(
                "/webhooks/sms/twilio-inbound",
                data={"From": "+14155570006", "Body": "STOP"},
            )

        assert response.status_code == 200
        # These queries would raise if the session were left in the aborted
        # transaction.
        assert await sms_opt_out.is_opted_out(db_session, "+14155570006")
        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED
        )
        assert rows == []


@pytest.mark.asyncio
class TestAccountHolderSubscriptionCancelledOutbox:
    async def test_sweep_with_cancelled_sub_enqueues_one_row_and_stamps_handled(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session,
            phone_number="+14155570101",
            full_name="Cara Cancelled",
            expo_push_token="ExponentPushToken[cara]",
        )
        sub = await create_test_subscription(db_session, user)
        sub.stripe_subscription_id = "sub_ah_101"
        await db_session.commit()
        await _backdate_opt_out(db_session, "+14155570101", days=15)

        with patch(
            "app.services.sms_unsubscribe_tasks.stripe_service."
            "cancel_subscription_at_period_end"
        ) as mock_cancel, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(user.expo_push_token)
            )
            processed = await process_unhandled_sms_unsubscribes(db_session)

        assert processed == 1
        mock_cancel.assert_called_once_with("sub_ah_101")

        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.channel == DeliveryChannel.PUSH
        assert row.recipient_user_id == user.id
        assert row.title == "Subscription set to cancel"
        assert "14 days" in row.body
        assert row.data == {"type": "account_holder_subscription_cancelled"}
        assert row.status == DeliveryStatus.SENT
        assert row.dedupe_key.endswith(str(sub.id))

        await db_session.refresh(user)
        assert user.sms_unsubscribe_handled_at is not None
        await db_session.refresh(sub)
        assert sub.auto_renew is False

    async def test_sweep_enqueue_failure_leaves_handled_at_null(
        self, db_session: AsyncSession
    ):
        """A DB-layer failure while enqueuing the row still raises out of
        `_act_on_unsubscribed_user`, so the sweep leaves `handled_at` NULL
        for the next tick — unlike a provider-side failure during the
        inline dispatch, which the reconciler retries instead."""
        user = await create_test_user(
            db_session,
            phone_number="+14155570102",
            full_name="Fay Failed",
            expo_push_token="ExponentPushToken[fay]",
        )
        sub = await create_test_subscription(db_session, user)
        sub.stripe_subscription_id = "sub_ah_102"
        await db_session.commit()
        await _backdate_opt_out(db_session, "+14155570102", days=15)

        with patch(
            "app.services.sms_unsubscribe_tasks.stripe_service."
            "cancel_subscription_at_period_end"
        ), patch(
            "app.services.notification_outbox.crud_nd.enqueue",
            new=AsyncMock(side_effect=RuntimeError("db down")),
        ):
            processed = await process_unhandled_sms_unsubscribes(db_session)

        assert processed == 0
        await db_session.refresh(user)
        assert user.sms_unsubscribe_handled_at is None
        await db_session.refresh(sub)
        # The deferred flip never ran either — local state stays in sync.
        assert sub.auto_renew is True
        assert sub.cancelled_by_sms_unsubscribe_at is None

    async def test_new_cancelled_sub_gets_a_fresh_occurrence(
        self, db_session: AsyncSession
    ):
        """occurrence = subscription id: a later, different subscription
        being cancelled for the same user is its own send, not deduped
        against an earlier cancellation."""
        user = await create_test_user(
            db_session, phone_number="+14155570103", full_name="Two Subs"
        )
        sub1 = await create_test_subscription(db_session, user)
        sub1.stripe_subscription_id = "sub_ah_103a"
        await db_session.commit()

        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(return_value=_expo_ok_for())
            await send_account_holder_subscription_cancelled(
                db_session, user, 14, subscription_id=sub1.id
            )
            await send_account_holder_subscription_cancelled(
                db_session, user, 14, subscription_id=sub1.id
            )

        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED
        )
        # Same sub id twice dedupes to one row.
        assert len(rows) == 1

        sub2 = await create_test_subscription(db_session, user)
        sub2.stripe_subscription_id = "sub_ah_103b"
        await db_session.commit()

        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(return_value=_expo_ok_for())
            await send_account_holder_subscription_cancelled(
                db_session, user, 14, subscription_id=sub2.id
            )

        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED
        )
        assert len(rows) == 2
        assert len({r.dedupe_key for r in rows}) == 2

    async def test_db_error_for_one_user_does_not_poison_the_rest_of_the_sweep(
        self, db_session: AsyncSession
    ):
        """A real DB error enqueuing one user's push aborts the transaction;
        the sweep rolls back that user only (handled_at NULL, auto_renew
        untouched) and still processes + commits the other user."""
        bad = await create_test_user(
            db_session,
            phone_number="+14155570104",
            full_name="Bad Enqueue",
            expo_push_token="ExponentPushToken[bad]",
        )
        good = await create_test_user(
            db_session,
            phone_number="+14155570105",
            full_name="Good Enqueue",
            expo_push_token="ExponentPushToken[good]",
        )
        bad_sub = await create_test_subscription(db_session, bad)
        bad_sub.stripe_subscription_id = "sub_ah_104"
        good_sub = await create_test_subscription(db_session, good)
        good_sub.stripe_subscription_id = "sub_ah_105"
        await db_session.commit()
        await _backdate_opt_out(db_session, "+14155570104", days=15)
        await _backdate_opt_out(db_session, "+14155570105", days=15)

        with patch(
            "app.services.sms_unsubscribe_tasks.stripe_service."
            "cancel_subscription_at_period_end"
        ), patch(
            "app.services.notification_outbox.crud_nd.enqueue",
            new=_enqueue_with_real_db_error({bad.id}),
        ), patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for("ExponentPushToken[good]")
            )
            processed = await process_unhandled_sms_unsubscribes(db_session)

        assert processed == 1
        await db_session.refresh(bad)
        await db_session.refresh(good)
        await db_session.refresh(bad_sub)
        await db_session.refresh(good_sub)
        assert bad.sms_unsubscribe_handled_at is None
        assert bad_sub.auto_renew is True
        assert good.sms_unsubscribe_handled_at is not None
        assert good_sub.auto_renew is False
        rows = await _rows_for_kind(
            db_session, NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED
        )
        assert [r.recipient_user_id for r in rows] == [good.id]
