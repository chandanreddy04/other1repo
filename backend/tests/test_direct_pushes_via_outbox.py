"""Every push is auditable via the notification outbox (owner decision).

Previously two call sites bypassed the outbox and called
`ExpoPushNotificationService.send_notification` directly — no delivery row,
no retry, no Expo receipt:

- `group_plan_service.grant_grace_period_to_members` (per-member push,
  `data={"type": "group_plan_grace"}`)
- `sub_lapse_notifications._send_to_user` (per-dependent SMS + push, called
  by `notify_lapse` for each lapse "moment")

Both now enqueue `NotificationDelivery` rows (kinds GROUP_PLAN_GRACE and
SUBSCRIPTION_LAPSE) and dispatch through the reconciler
(`app.services.notification_outbox`), so this file asserts outbox rows
rather than direct provider calls — patch targets follow
`test_no_stale_dispatch_patches.py`'s rule (patch the reconciler, not the
enqueue-only service module).

Related: app/services/group_plan_service.py, app/services/sub_lapse_notifications.py,
         app/services/notification_outbox.py, app/services/notification_policy.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.group_plan import GroupPlan, GroupPlanMember, GroupPlanMemberRole
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.subscription import (
    PlanType,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.services import group_plan_service, sms_opt_out, sub_lapse_notifications
from app.services.notification_policy import POLICIES
from app.services.sms import SMSResult
from app.services.sub_lapse_notifications import Moment, notify_lapse
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


class TestPolicyInvariants:
    def test_new_kinds_are_receipt_tracked(self):
        # Both kinds carry a PUSH channel, so the outbox reconciler must poll
        # Expo receipts for them — the invariant test_circle_alerts_sms_only.py
        # pins (track_expo_receipts == has_push for every kind) covers this
        # too; asserted directly here for the two kinds this file covers.
        assert POLICIES[NotificationKind.GROUP_PLAN_GRACE].track_expo_receipts is True
        assert POLICIES[NotificationKind.SUBSCRIPTION_LAPSE].track_expo_receipts is True

    def test_new_kinds_are_not_circle_directed(self):
        from app.services.notification_policy import CIRCLE_DIRECTED_KINDS

        assert NotificationKind.GROUP_PLAN_GRACE not in CIRCLE_DIRECTED_KINDS
        assert NotificationKind.SUBSCRIPTION_LAPSE not in CIRCLE_DIRECTED_KINDS
        assert POLICIES[NotificationKind.GROUP_PLAN_GRACE].escalate_on_exhausted is False
        assert (
            POLICIES[NotificationKind.SUBSCRIPTION_LAPSE].escalate_on_exhausted is False
        )


@pytest.mark.asyncio
class TestGrantGracePeriodOutbox:
    async def _setup_plan(self, db_session: AsyncSession, *, prefix: str):
        owner = await create_test_user(
            db_session, phone_number=f"+1415560{prefix}0", full_name="Olive Owner"
        )
        member_with_token = await create_test_user(
            db_session,
            phone_number=f"+1415560{prefix}1",
            full_name="Milo Member",
            expo_push_token="ExponentPushToken[milo]",
        )
        member_no_token = await create_test_user(
            db_session, phone_number=f"+1415560{prefix}2", full_name="Nora NoToken"
        )
        sub = Subscription(
            user_id=owner.id,
            phone_number_id=owner.phone_number_id,
            plan_type=PlanType.GROUP_MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            source=SubscriptionSource.ADMIN,
            current_period_start=datetime.now(UTC) - timedelta(days=30),
            current_period_end=datetime.now(UTC),
        )
        db_session.add(sub)
        await db_session.flush()
        plan = GroupPlan(
            owner_user_id=owner.id,
            subscription_id=sub.id,
            invite_code=f"GRACE{prefix}",
        )
        db_session.add(plan)
        await db_session.flush()
        db_session.add_all(
            [
                GroupPlanMember(
                    group_plan_id=plan.id,
                    user_id=owner.id,
                    role=GroupPlanMemberRole.OWNER.value,
                ),
                GroupPlanMember(
                    group_plan_id=plan.id,
                    user_id=member_with_token.id,
                    role=GroupPlanMemberRole.MEMBER.value,
                ),
                GroupPlanMember(
                    group_plan_id=plan.id,
                    user_id=member_no_token.id,
                    role=GroupPlanMemberRole.MEMBER.value,
                ),
            ]
        )
        await db_session.commit()
        return owner, member_with_token, member_no_token, plan

    async def test_one_push_row_per_non_owner_member(self, db_session: AsyncSession):
        _owner, with_token, no_token, plan = await self._setup_plan(
            db_session, prefix="1"
        )

        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(with_token.expo_push_token)
            )
            await group_plan_service.grant_grace_period_to_members(
                db_session, plan, days=7
            )

        rows = await _rows_for_kind(db_session, NotificationKind.GROUP_PLAN_GRACE)
        by_user = {r.recipient_user_id: r for r in rows}

        # Exactly one row per non-owner member; none for the owner.
        assert set(by_user) == {with_token.id, no_token.id}
        assert all(r.channel == DeliveryChannel.PUSH for r in rows)

        # Expected title/body/data.
        sent = by_user[with_token.id]
        assert sent.title == "Your Group Plan has ended"
        assert "Olive" in sent.body
        assert "7 days" in sent.body
        assert sent.data == {"type": "group_plan_grace"}
        assert sent.status == DeliveryStatus.SENT

        # A member with an account but no push token gets a REFUSED row
        # (the outbox's existing convention — _dispatch_push marks "no push
        # token" REFUSED — not a silent skip).
        refused = by_user[no_token.id]
        assert refused.status == DeliveryStatus.REFUSED
        assert refused.last_error == "no push token"
        assert refused.data == {"type": "group_plan_grace"}

    async def test_running_twice_does_not_repush(self, db_session: AsyncSession):
        """The dedupe key is (plan, member): a second run for the same plan
        (e.g. a re-processed subscription.deleted) enqueues nothing new and
        the provider is called once in total."""
        _owner, with_token, no_token, plan = await self._setup_plan(
            db_session, prefix="2"
        )

        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(with_token.expo_push_token)
            )
            await group_plan_service.grant_grace_period_to_members(
                db_session, plan, days=7
            )
            await group_plan_service.grant_grace_period_to_members(
                db_session, plan, days=7
            )

        rows = await _rows_for_kind(db_session, NotificationKind.GROUP_PLAN_GRACE)
        assert sorted(str(r.recipient_user_id) for r in rows) == sorted(
            [str(with_token.id), str(no_token.id)]
        )
        assert mock_push_cls.send_notification.await_count == 1
        assert (
            mock_push_cls.send_notification.await_args.kwargs["push_tokens"]
            == [with_token.expo_push_token]
        )


@pytest.mark.asyncio
class TestSubscriptionLapseOutbox:
    async def test_group_sub_enqueues_sms_and_push_with_identical_text(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155561001", full_name="Gina Group"
        )
        member = await create_test_user(
            db_session,
            phone_number="+14155561002",
            full_name="Mo Member",
            expo_push_token="ExponentPushToken[mo]",
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
        sub.current_period_end = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        await db_session.commit()
        await db_session.refresh(sub)

        with patch(
            "app.services.notification_outbox.sms_opt_out"
        ) as mock_sms, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_sms.gated_send_sms = AsyncMock(
                return_value=SMSResult(success=True, message_id="sm_1", error=None)
            )
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(member.expo_push_token)
            )
            counts = await notify_lapse(db_session, sub, Moment.T_ZERO)

        assert counts == {"sms_sent": 1, "push_sent": 1}

        expected_sms = sub_lapse_notifications._GROUP_SMS[Moment.T_ZERO].format(
            owner_name=owner.full_name,
            date=sub_lapse_notifications._format_date(sub.current_period_end.date()),
        )
        expected_push_body = sub_lapse_notifications._PUSH_BODY[Moment.T_ZERO]

        rows = await _rows_for_kind(db_session, NotificationKind.SUBSCRIPTION_LAPSE)
        sms_row = next(r for r in rows if r.channel == DeliveryChannel.SMS)
        push_row = next(r for r in rows if r.channel == DeliveryChannel.PUSH)

        # Byte-identical to what the old direct path sent.
        assert sms_row.body == expected_sms
        assert sms_row.status == DeliveryStatus.SENT
        assert push_row.body == expected_push_body
        assert push_row.title == "Your access is ending"
        assert push_row.status == DeliveryStatus.SENT
        assert push_row.data == {"type": "subscription_lapse"}

    async def test_sponsored_sub_enqueues_sms_and_push_with_identical_text(
        self, db_session: AsyncSession
    ):
        sponsor = await create_test_user(
            db_session, phone_number="+14155564567", full_name="Sponsor"
        )
        beneficiary = await create_test_user(
            db_session,
            phone_number="+14155565000",
            full_name="Beneficiary",
            expo_push_token="ExponentPushToken[bene]",
        )
        sub = await create_test_subscription(
            db_session,
            beneficiary,
            plan_type="monthly",
            source=SubscriptionSource.STRIPE_GIFT.value,
        )
        sub.gifted_by_phone_id = sponsor.phone_number_id
        sub.current_period_end = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
        await db_session.commit()
        await db_session.refresh(sub)

        with patch(
            "app.services.notification_outbox.sms_opt_out"
        ) as mock_sms, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_sms.gated_send_sms = AsyncMock(
                return_value=SMSResult(success=True, message_id="sm_2", error=None)
            )
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(beneficiary.expo_push_token)
            )
            counts = await notify_lapse(db_session, sub, Moment.T_MINUS_7D)

        assert counts == {"sms_sent": 1, "push_sent": 1}

        expected_sms = sub_lapse_notifications._SPONSOR_SMS[Moment.T_MINUS_7D].format(
            sponsor_phone_full=sub_lapse_notifications._format_international(
                sponsor.phone_number
            ),
            date=sub_lapse_notifications._format_date(sub.current_period_end.date()),
        )

        rows = await _rows_for_kind(db_session, NotificationKind.SUBSCRIPTION_LAPSE)
        sms_row = next(r for r in rows if r.channel == DeliveryChannel.SMS)
        assert sms_row.body == expected_sms
        assert sms_row.status == DeliveryStatus.SENT

    async def test_opted_out_dependent_gets_no_successful_sms(
        self, db_session: AsyncSession
    ):
        """Real opt-out gating (no mock on gated_send_sms) — the dependent's
        phone is marked opted-out and the SMS row must land REFUSED, matching
        the outbox's existing opt-out convention (never silently dropped)."""
        owner = await create_test_user(
            db_session, phone_number="+14155566001", full_name="Gia"
        )
        member = await create_test_user(
            db_session, phone_number="+14155566002", full_name="Otis"
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
        await sms_opt_out.record_opt_out(db_session, member.phone_number)
        await db_session.commit()
        await db_session.refresh(sub)

        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(return_value=_expo_ok_for())
            counts = await notify_lapse(db_session, sub, Moment.T_ZERO)

        # No successful SMS counted for the opted-out member.
        assert counts["sms_sent"] == 0

        rows = await _rows_for_kind(db_session, NotificationKind.SUBSCRIPTION_LAPSE)
        sms_row = next(r for r in rows if r.channel == DeliveryChannel.SMS)
        assert sms_row.status == DeliveryStatus.REFUSED
        assert sms_row.last_error == "opted_out"


async def _group_sub_with_member(db: AsyncSession, *, prefix: str):
    owner = await create_test_user(
        db, phone_number=f"+1415557{prefix}01", full_name="Dee Dupe"
    )
    member = await create_test_user(
        db,
        phone_number=f"+1415557{prefix}02",
        full_name="Max Member",
        expo_push_token=f"ExponentPushToken[max{prefix}]",
    )
    sub = await create_test_subscription(db, owner, plan_type="group_monthly")
    plan = await group_plan_service.create_group_plan(
        db, owner=owner, subscription_id=sub.id
    )
    await group_plan_service.join_plan(db, user=member, invite_code=plan.invite_code)
    sub.current_period_end = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    await db.commit()
    await db.refresh(sub)
    return sub, member


@pytest.mark.asyncio
class TestSubscriptionLapseDedupe:
    async def test_same_moment_same_period_sends_once(
        self, db_session: AsyncSession
    ):
        """One send per moment per billing period: a second T_ZERO in the same
        period (another trigger, or a re-run) enqueues nothing and calls
        neither provider again."""
        sub, member = await _group_sub_with_member(db_session, prefix="1")

        with patch(
            "app.services.notification_outbox.sms_opt_out"
        ) as mock_sms, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_sms.gated_send_sms = AsyncMock(
                return_value=SMSResult(success=True, message_id="sm_d", error=None)
            )
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(member.expo_push_token)
            )
            await notify_lapse(db_session, sub, Moment.T_ZERO)
            await notify_lapse(db_session, sub, Moment.T_ZERO)

        rows = await _rows_for_kind(db_session, NotificationKind.SUBSCRIPTION_LAPSE)
        assert sorted(r.channel for r in rows) == sorted(
            [DeliveryChannel.PUSH, DeliveryChannel.SMS]
        )
        assert mock_sms.gated_send_sms.await_count == 1
        assert mock_push_cls.send_notification.await_count == 1

    async def test_new_billing_period_gets_fresh_rows(
        self, db_session: AsyncSession
    ):
        """A later lapse cycle (new current_period_end) is a new occurrence:
        the same moment sends again, with the new period's date."""
        sub, member = await _group_sub_with_member(db_session, prefix="2")

        with patch(
            "app.services.notification_outbox.sms_opt_out"
        ) as mock_sms, patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_sms.gated_send_sms = AsyncMock(
                return_value=SMSResult(success=True, message_id="sm_p", error=None)
            )
            mock_push_cls.send_notification = AsyncMock(
                return_value=_expo_ok_for(member.expo_push_token)
            )
            await notify_lapse(db_session, sub, Moment.T_ZERO)
            sub.current_period_end = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
            await db_session.commit()
            await notify_lapse(db_session, sub, Moment.T_ZERO)

        rows = await _rows_for_kind(db_session, NotificationKind.SUBSCRIPTION_LAPSE)
        sms_rows = [r for r in rows if r.channel == DeliveryChannel.SMS]
        push_rows = [r for r in rows if r.channel == DeliveryChannel.PUSH]
        assert len(sms_rows) == 2
        assert len(push_rows) == 2
        assert sorted("Aug 1" in r.body for r in sms_rows) == [False, True]
        assert sorted("Sep 1" in r.body for r in sms_rows) == [False, True]
        assert mock_sms.gated_send_sms.await_count == 2
        assert mock_push_cls.send_notification.await_count == 2
