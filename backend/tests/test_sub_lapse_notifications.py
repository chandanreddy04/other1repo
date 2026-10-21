"""Tests for sub_lapse_notifications.notify_lapse fan-out.

`_send_to_user` does not call the SMS/push providers directly —
it enqueues notification_deliveries rows (kind SUBSCRIPTION_LAPSE) and
dispatches inline via the reconciler (`app.services.notification_outbox`).
Dispatch mocks are therefore patched on `notification_outbox`, not on
`sub_lapse_notifications` (which no longer imports either provider) — see
`test_no_stale_dispatch_patches.py`.

Related: app/services/sub_lapse_notifications.py,
         app/services/notification_outbox.py,
         docs/account-deletion-plan.md (notification surface)
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.subscription import SubscriptionSource
from app.models.user import User
from app.services import group_plan_service, sub_lapse_notifications
from app.services.sms import SMSResult
from app.services.sub_lapse_notifications import Moment, notify_lapse
from tests.helpers import (
    create_test_subscription,
    create_test_user,
)


def _sms_ok() -> SMSResult:
    return SMSResult(success=True, message_id="sm_x", error=None)


async def _expo_accept_all(*, push_tokens: list[str], **_kwargs) -> dict:
    """Expo accepts every token — the real ExpoPushNotificationService result
    shape the reconciler reads (ok_tokens / dead_tokens / ticket_ids)."""
    return {
        "ok_tokens": list(push_tokens),
        "dead_tokens": [],
        "ticket_ids": {t: f"ticket-{t}" for t in push_tokens},
    }


async def _lapse_rows(db: AsyncSession, *, user: User) -> list[NotificationDelivery]:
    """Both delivery rows (PUSH keyed by recipient_user_id, SMS by
    recipient_phone_id) for one dependent's SUBSCRIPTION_LAPSE fan-out."""
    result = await db.execute(
        select(NotificationDelivery).where(
            NotificationDelivery.kind == NotificationKind.SUBSCRIPTION_LAPSE,
            or_(
                NotificationDelivery.recipient_user_id == user.id,
                NotificationDelivery.recipient_phone_id == user.phone_number_id,
            ),
        )
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
class TestGroupDependents:
    async def test_t_zero_renders_owner_name_and_date(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550001", full_name="Sam Owner"
        )
        owner.expo_push_token = "ExponentPushToken[owner]"
        member = await create_test_user(
            db_session, phone_number="+14155550002", full_name="Pat Member"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type="group_monthly"
        )
        plan = await group_plan_service.create_group_plan(
            db_session, owner=owner, subscription_id=sub.id
        )
        await group_plan_service.join_plan(
            db_session, user=member, invite_code=plan.invite_code
        )

        sub.current_period_end = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
        await db_session.commit()

        with patch(
            "app.services.notification_outbox.sms_opt_out"
        ) as mock_sms, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_sms.gated_send_sms = AsyncMock(return_value=_sms_ok())
            mock_push_cls.send_notification = AsyncMock(side_effect=_expo_accept_all)
            counts = await notify_lapse(db_session, sub, Moment.T_ZERO)

        assert counts == {"sms_sent": 1, "push_sent": 0}
        sent_args = mock_sms.gated_send_sms.await_args.args
        sent_body = sent_args[2]
        assert "Sam Owner" in sent_body
        assert "Jul 6" in sent_body
        assert "https://madeitho.me/sub" in sent_body
        # Owner does NOT get an SMS; they're the one who lapsed.
        assert sent_args[1] == "+14155550002"

        # The outbox row is the auditable record — SMS body byte-identical
        # to what was actually sent, push REFUSED (member has no token).
        rows = await _lapse_rows(db_session, user=member)
        by_channel = {r.channel: r for r in rows}
        assert by_channel[DeliveryChannel.SMS].body == sent_body
        assert by_channel[DeliveryChannel.SMS].status == DeliveryStatus.SENT
        assert by_channel[DeliveryChannel.PUSH].status == DeliveryStatus.REFUSED
        assert by_channel[DeliveryChannel.PUSH].data["type"] == "subscription_lapse"

    async def test_owner_purged_falls_back_to_generic_string(
        self, db_session: AsyncSession
    ):
        """After hard-purge of the owner (full_name=NULL), the T=0 SMS
        substitutes 'the plan owner' so we don't ship a bare {owner_name}."""
        owner = await create_test_user(
            db_session, phone_number="+14155550003", full_name="Will Be Purged"
        )
        member = await create_test_user(
            db_session, phone_number="+14155550004", full_name="Pat Member"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type="group_monthly"
        )
        plan = await group_plan_service.create_group_plan(
            db_session, owner=owner, subscription_id=sub.id
        )
        await group_plan_service.join_plan(
            db_session, user=member, invite_code=plan.invite_code
        )
        # Simulate hard-purge.
        owner.full_name = None
        await db_session.commit()

        with patch(
            "app.services.notification_outbox.sms_opt_out"
        ) as mock_sms, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_sms.gated_send_sms = AsyncMock(return_value=_sms_ok())
            mock_push_cls.send_notification = AsyncMock(side_effect=_expo_accept_all)
            await notify_lapse(db_session, sub, Moment.T_ZERO)

        sent_body = mock_sms.gated_send_sms.await_args.args[2]
        assert "the plan owner" in sent_body

    async def test_reminder_moments_use_generic_template(
        self, db_session: AsyncSession
    ):
        """T-7d / T-1d / T-end templates don't substitute owner name —
        they're short reminders, not status updates."""
        owner = await create_test_user(
            db_session, phone_number="+14155550005", full_name="Sam"
        )
        member = await create_test_user(
            db_session, phone_number="+14155550006", full_name="Pat"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type="group_annual"
        )
        plan = await group_plan_service.create_group_plan(
            db_session, owner=owner, subscription_id=sub.id
        )
        await group_plan_service.join_plan(
            db_session, user=member, invite_code=plan.invite_code
        )

        for moment, expected_fragment in [
            (Moment.T_MINUS_7D, "ends in 7 days"),
            (Moment.T_MINUS_1D, "ends tomorrow"),
            (Moment.T_END, "ended today"),
        ]:
            with patch(
                "app.services.notification_outbox.sms_opt_out"
            ) as mock_sms, patch(
                "app.services.notification_outbox.ExpoPushNotificationService"
            ) as mock_push_cls:
                mock_sms.gated_send_sms = AsyncMock(return_value=_sms_ok())
                mock_push_cls.send_notification = AsyncMock(side_effect=_expo_accept_all)
                await notify_lapse(db_session, sub, moment)
            sent_body = mock_sms.gated_send_sms.await_args.args[2]
            assert expected_fragment in sent_body.lower()


@pytest.mark.asyncio
class TestSponsoredBeneficiary:
    async def test_t_zero_includes_sponsor_phone_international(
        self, db_session: AsyncSession
    ):
        sponsor = await create_test_user(
            db_session, phone_number="+14155554567", full_name="Sponsor"
        )
        beneficiary = await create_test_user(
            db_session, phone_number="+14155555000", full_name="Beneficiary"
        )
        sub = await create_test_subscription(
            db_session,
            beneficiary,
            plan_type="monthly",
            source=SubscriptionSource.STRIPE_GIFT.value,
        )
        sub.gifted_by_phone_id = sponsor.phone_number_id
        sub.current_period_end = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
        await db_session.commit()
        await db_session.refresh(sub)

        with patch(
            "app.services.notification_outbox.sms_opt_out"
        ) as mock_sms, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_sms.gated_send_sms = AsyncMock(return_value=_sms_ok())
            mock_push_cls.send_notification = AsyncMock(side_effect=_expo_accept_all)
            counts = await notify_lapse(db_session, sub, Moment.T_ZERO)

        assert counts["sms_sent"] == 1
        body = mock_sms.gated_send_sms.await_args.args[2]
        # International format: "+1 (415) 555-4567" or similar; just check
        # the sponsor digits appear and the +1 prefix is present.
        assert "+1" in body
        assert "415" in body
        assert "Jul 6" in body


@pytest.mark.asyncio
class TestSponsoredEdgeCases:
    async def test_sponsor_phone_unset_skips_dispatch(
        self, db_session: AsyncSession
    ):
        """If the gifter side of a STRIPE_GIFT sub is missing (data
        corruption / migrated row / hard-purged sponsor with severed
        phone link), we have no `{sponsor_phone_full}` to render — skip
        the SMS rather than ship a template with the placeholder bare."""
        beneficiary = await create_test_user(
            db_session, phone_number="+14155555100", full_name="Solo Bene"
        )
        sub = await create_test_subscription(
            db_session,
            beneficiary,
            plan_type="monthly",
            source=SubscriptionSource.STRIPE_GIFT.value,
        )
        # No gifted_by_phone_id set.

        with patch("app.services.notification_outbox.sms_opt_out") as mock_sms:
            mock_sms.gated_send_sms = AsyncMock(return_value=_sms_ok())
            counts = await notify_lapse(db_session, sub, Moment.T_ZERO)

        assert counts == {"sms_sent": 0, "push_sent": 0}
        mock_sms.gated_send_sms.assert_not_called()
        assert await _lapse_rows(db_session, user=beneficiary) == []


@pytest.mark.asyncio
class TestNonGroupNonGifted:
    async def test_individual_sub_has_no_dependents(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155556000", full_name="Solo"
        )
        sub = await create_test_subscription(db_session, user, plan_type="monthly")

        with patch("app.services.notification_outbox.sms_opt_out") as mock_sms:
            mock_sms.gated_send_sms = AsyncMock(return_value=_sms_ok())
            counts = await notify_lapse(db_session, sub, Moment.T_ZERO)

        assert counts == {"sms_sent": 0, "push_sent": 0}
        mock_sms.gated_send_sms.assert_not_called()


@pytest.mark.asyncio
class TestProcessPendingLapseReminders:
    async def _setup_cancelling_sub(
        self, db_session, *, phone, period_end_offset_days, plan_type="group_monthly"
    ):
        owner = await create_test_user(db_session, phone_number=phone, full_name="X")
        member_phone = phone[:-1] + str((int(phone[-1]) + 1) % 10)
        member = await create_test_user(
            db_session, phone_number=member_phone, full_name="Member"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=plan_type
        )
        sub.auto_renew = False
        sub.current_period_end = datetime.now(UTC) + timedelta(
            days=period_end_offset_days
        )
        plan = await group_plan_service.create_group_plan(
            db_session, owner=owner, subscription_id=sub.id
        )
        await group_plan_service.join_plan(
            db_session, user=member, invite_code=plan.invite_code
        )
        await db_session.commit()
        await db_session.refresh(sub)
        return sub

    async def test_fires_7d_in_window(self, db_session: AsyncSession):
        sub = await self._setup_cancelling_sub(
            db_session, phone="+14155551000", period_end_offset_days=5
        )
        with patch(
            "app.services.sub_lapse_notifications.notify_lapse",
            new=AsyncMock(return_value={"sms_sent": 1, "push_sent": 0}),
        ) as mock_notify:
            counts = await sub_lapse_notifications.process_pending_lapse_reminders(
                db_session
            )

        assert counts["reminders_sent"] == 1
        assert mock_notify.await_args.args[2] == Moment.T_MINUS_7D
        await db_session.refresh(sub)
        assert sub.lapse_reminder_7d_sent_at is not None
        assert sub.lapse_reminder_1d_sent_at is None

    async def test_fires_1d_in_window(self, db_session: AsyncSession):
        sub = await self._setup_cancelling_sub(
            db_session, phone="+14155551001", period_end_offset_days=0.5
        )
        # T-7d already sent in a prior tick.
        sub.lapse_reminder_7d_sent_at = datetime.now(UTC) - timedelta(days=6)
        await db_session.commit()

        with patch(
            "app.services.sub_lapse_notifications.notify_lapse",
            new=AsyncMock(return_value={"sms_sent": 1, "push_sent": 0}),
        ) as mock_notify:
            counts = await sub_lapse_notifications.process_pending_lapse_reminders(
                db_session
            )

        assert counts["reminders_sent"] == 1
        assert mock_notify.await_args.args[2] == Moment.T_MINUS_1D

    async def test_skips_already_sent(self, db_session: AsyncSession):
        sub = await self._setup_cancelling_sub(
            db_session, phone="+14155551002", period_end_offset_days=5
        )
        # Already sent the 7-day reminder.
        sub.lapse_reminder_7d_sent_at = datetime.now(UTC) - timedelta(hours=1)
        await db_session.commit()

        with patch(
            "app.services.sub_lapse_notifications.notify_lapse",
            new=AsyncMock(),
        ) as mock_notify:
            counts = await sub_lapse_notifications.process_pending_lapse_reminders(
                db_session
            )

        assert counts["reminders_sent"] == 0
        mock_notify.assert_not_called()

    async def test_skips_auto_renewing_subs(self, db_session: AsyncSession):
        """A sub that's still set to auto-renew isn't ending — don't
        send a lapse reminder."""
        sub = await self._setup_cancelling_sub(
            db_session, phone="+14155551003", period_end_offset_days=5
        )
        sub.auto_renew = True
        await db_session.commit()

        with patch(
            "app.services.sub_lapse_notifications.notify_lapse",
            new=AsyncMock(),
        ) as mock_notify:
            counts = await sub_lapse_notifications.process_pending_lapse_reminders(
                db_session
            )

        assert counts["reminders_sent"] == 0
        mock_notify.assert_not_called()

    async def test_only_t_1d_fires_when_period_end_under_1_day(
        self, db_session: AsyncSession
    ):
        """A sub cancelled with <1 day to go must NOT receive 'ends in
        7 days' — the 7-day window's lower bound is `now + 1d` so the
        sub falls into T-1d only. Regression for a window-overlap bug
        where both reminders would fire in the same tick."""
        sub = await self._setup_cancelling_sub(
            db_session, phone="+14155551005", period_end_offset_days=0.5
        )

        with patch(
            "app.services.sub_lapse_notifications.notify_lapse",
            new=AsyncMock(return_value={"sms_sent": 1, "push_sent": 0}),
        ) as mock_notify:
            counts = await sub_lapse_notifications.process_pending_lapse_reminders(
                db_session
            )

        assert counts["reminders_sent"] == 1
        # Exactly one call, and it's T_MINUS_1D.
        assert mock_notify.await_count == 1
        assert mock_notify.await_args.args[2] == Moment.T_MINUS_1D
        await db_session.refresh(sub)
        # 7d stamp stays NULL — we explicitly skipped it.
        assert sub.lapse_reminder_7d_sent_at is None
        assert sub.lapse_reminder_1d_sent_at is not None

    async def test_skips_already_past_period_end(
        self, db_session: AsyncSession
    ):
        # Set up while still in the future (join_plan validates), then
        # move the period_end backwards to simulate "the period has now
        # passed but the worker is somehow seeing it."
        sub = await self._setup_cancelling_sub(
            db_session, phone="+14155551004", period_end_offset_days=5
        )
        sub.current_period_end = datetime.now(UTC) - timedelta(days=1)
        await db_session.commit()

        with patch(
            "app.services.sub_lapse_notifications.notify_lapse",
            new=AsyncMock(),
        ) as mock_notify:
            counts = await sub_lapse_notifications.process_pending_lapse_reminders(
                db_session
            )

        assert counts["reminders_sent"] == 0
        mock_notify.assert_not_called()


@pytest.mark.asyncio
class TestFanOutResilience:
    async def test_one_member_failure_does_not_block_others(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155557000", full_name="Sam"
        )
        m1 = await create_test_user(
            db_session, phone_number="+14155557001", full_name="P1"
        )
        m2 = await create_test_user(
            db_session, phone_number="+14155557002", full_name="P2"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type="group_monthly"
        )
        plan = await group_plan_service.create_group_plan(
            db_session, owner=owner, subscription_id=sub.id
        )
        await group_plan_service.join_plan(
            db_session, user=m1, invite_code=plan.invite_code
        )
        await group_plan_service.join_plan(
            db_session, user=m2, invite_code=plan.invite_code
        )

        call_count = {"n": 0}

        async def flaky_sms(db, to_phone, message, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient")
            return _sms_ok()

        with patch(
            "app.services.notification_outbox.sms_opt_out"
        ) as mock_sms, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_sms.gated_send_sms = AsyncMock(side_effect=flaky_sms)
            mock_push_cls.send_notification = AsyncMock(side_effect=_expo_accept_all)
            counts = await notify_lapse(db_session, sub, Moment.T_ZERO)

        # One failed, one succeeded — the reconciler catches the provider
        # exception per-row (backs the row off) rather than raising, so
        # both members get an outbox row; only the succeeding one counts.
        assert counts["sms_sent"] == 1

        m1_rows = await _lapse_rows(db_session, user=m1)
        m2_rows = await _lapse_rows(db_session, user=m2)
        statuses = [
            r.status
            for rows in (m1_rows, m2_rows)
            for r in rows
            if r.channel == DeliveryChannel.SMS
        ]
        assert statuses.count(DeliveryStatus.SENT) == 1
        assert statuses.count(DeliveryStatus.FAILED) == 1
