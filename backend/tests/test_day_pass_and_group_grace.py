"""Day pass ($0.99 / 24h) + group-plan lapse grace notification.

Covers the 2026-07-02 flow-review decisions (docs/flow-review.md 3.9,
E3/§4.2): a one-time Stripe payment grants a DAY_PASS subscription row
covering DAY_PASS_HOURS (riding the normal check_access 'subscription'
path), and group members get a push when the owner's plan lapses instead
of silently losing access a week later.

Related: app/api/v1/endpoints/webhooks.py (_handle_day_pass_checkout),
app/api/v1/endpoints/subscriptions.py (POST /day-pass),
app/services/group_plan_service.py (grant_grace_period_to_members).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints.webhooks import _handle_day_pass_checkout
from app.core.config import settings
from app.models.group_plan import (
    GroupPlan,
    GroupPlanMember,
    GroupPlanMemberRole,
)
from app.models.notification_delivery import (
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
from app.services import subscription_service
from app.services.group_plan_service import grant_grace_period_to_members
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestDayPassGrant:
    async def test_webhook_grants_24h_day_pass(self, db_session: AsyncSession):
        user = await create_test_user(
            db_session, phone_number="+14155598001", full_name="Night Out"
        )
        await _handle_day_pass_checkout(
            db_session,
            session={"id": "cs_test_daypass"},
            metadata={"type": "day_pass", "user_id": str(user.id)},
        )
        await db_session.commit()

        sub = await subscription_service.get_active_subscription(db_session, user.id)
        assert sub is not None
        assert sub.plan_type == PlanType.DAY_PASS.value
        assert sub.auto_renew is False
        expected_end = datetime.now(UTC) + timedelta(hours=settings.DAY_PASS_HOURS)
        assert abs((sub.current_period_end - expected_end).total_seconds()) < 60

        # And it rides the normal access path.
        access = await subscription_service.check_access(db_session, user)
        assert access.has_access is True
        assert access.reason == "subscription"

    async def test_webhook_tolerates_unknown_user(self, db_session: AsyncSession):
        # Must not raise — webhook handlers log and move on.
        await _handle_day_pass_checkout(
            db_session,
            session={"id": "cs_test_daypass2"},
            metadata={
                "type": "day_pass",
                "user_id": "00000000-0000-0000-0000-000000000000",
            },
        )


@pytest.mark.asyncio
class TestGroupGraceNotification:
    async def test_members_get_grace_push_on_lapse(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155598003", full_name="Olive Owner"
        )
        member = await create_test_user(
            db_session, phone_number="+14155598004", full_name="Milo Member"
        )
        member.expo_push_token = "ExponentPushToken[group-grace-test]"
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
            invite_code="FAMGRACE",
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
                    user_id=member.id,
                    role=GroupPlanMemberRole.MEMBER.value,
                ),
            ]
        )
        await db_session.commit()

        # The push is routed through the outbox reconciler (owner decision:
        # every push auditable) —
        # patch the provider where dispatch actually happens
        # (app.services.notification_outbox), not on group_plan_service
        # (which only enqueues). See test_no_stale_dispatch_patches.py.
        with patch(
            "app.services.notification_outbox.ExpoPushNotificationService"
        ) as mock_push_cls:
            mock_push_cls.send_notification = AsyncMock(
                return_value={
                    "ok_tokens": [member.expo_push_token],
                    "dead_tokens": [],
                    "ticket_ids": {member.expo_push_token: "ticket-1"},
                }
            )
            await grant_grace_period_to_members(db_session, plan, days=7)

        # Member got credit + the lapse push; owner got neither.
        await db_session.refresh(member)
        assert member.free_credit_end is not None
        grace_calls = [
            c
            for c in mock_push_cls.send_notification.await_args_list
            if c.kwargs.get("data", {}).get("type") == "group_plan_grace"
        ]
        assert len(grace_calls) == 1
        body = grace_calls[0].kwargs["body"]
        assert "Olive" in body
        assert "7 days" in body

        # Auditable: exactly one GROUP_PLAN_GRACE delivery row for the
        # member (PUSH, sent), none for the owner — same title/body/data
        # the provider actually received, now durable in the outbox.
        rows = (
            (
                await db_session.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.kind == NotificationKind.GROUP_PLAN_GRACE
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.recipient_user_id == member.id
        assert row.status == DeliveryStatus.SENT
        assert row.body == body
        assert row.data == {"type": "group_plan_grace"}
