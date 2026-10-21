"""Regression for group-plan #2: a member who left can rejoin the same plan.

Previously join_plan always INSERTed a new GroupPlanMember row, which collided
with uq_fpm_plan_user for a user who had left that plan before (left_at set) and
500'd. join_plan now revives the prior row instead.

Related: app/services/group_plan_service.py.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.subscription import PlanType
from app.services import group_plan_service
from tests.helpers import (
    create_test_group_plan,
    create_test_subscription,
    create_test_user,
)


@pytest.mark.asyncio
async def test_rejoin_after_leaving_revives_membership(db_session: AsyncSession):
    owner = await create_test_user(db_session, phone_number="+14155565001")
    sub = await create_test_subscription(
        db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
    )
    plan = await create_test_group_plan(db_session, owner, sub)

    joiner = await create_test_user(db_session, phone_number="+14155565002")
    first = await group_plan_service.join_plan(
        db_session, invite_code=plan.invite_code, user=joiner
    )

    # Simulate leaving the plan.
    first.left_at = datetime.now(UTC)
    await db_session.commit()

    # Rejoin must succeed by reviving the same row, not 500 on the unique
    # collision.
    again = await group_plan_service.join_plan(
        db_session, invite_code=plan.invite_code, user=joiner
    )
    assert again.id == first.id
    assert again.left_at is None
