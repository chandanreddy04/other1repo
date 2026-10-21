"""Tests for group plan service and API endpoints."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.group_plan import crud_group_plan_member
from app.models.group_plan import GroupPlanMemberRole
from app.models.subscription import (
    PlanType,
)
from app.models.user import User
from app.services import group_plan_service, subscription_service
from tests.helpers import (
    create_test_group_plan,
    create_test_subscription,
    create_test_user,
)


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------
class TestGroupPlanService:
    async def test_create_group_plan(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550001", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )

        plan = await group_plan_service.create_group_plan(
            db_session, owner=owner, subscription_id=sub.id
        )

        assert plan.owner_user_id == owner.id
        assert plan.subscription_id == sub.id
        assert plan.invite_code is not None
        assert plan.max_members == 5

        members = await crud_group_plan_member.get_active_members(
            db_session, group_plan_id=plan.id
        )
        assert len(members) == 1
        assert members[0].user_id == owner.id
        assert members[0].role == GroupPlanMemberRole.OWNER.value

    async def test_join_plan(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550010", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550011", full_name="Joiner"
        )
        member = await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        assert member.user_id == joiner.id
        assert member.role == GroupPlanMemberRole.MEMBER.value
        assert member.left_at is None

    async def test_join_plan_rejects_full(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550020", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await group_plan_service.create_group_plan(
            db_session, owner=owner, subscription_id=sub.id, max_members=2
        )

        joiner1 = await create_test_user(
            db_session, phone_number="+14155550021", full_name="J1"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner1
        )

        joiner2 = await create_test_user(
            db_session, phone_number="+14155550022", full_name="J2"
        )
        with pytest.raises(Exception, match="full"):
            await group_plan_service.join_plan(
                db_session, invite_code=plan.invite_code, user=joiner2
            )

    async def test_join_plan_rejects_already_in_plan(self, db_session: AsyncSession):
        owner1 = await create_test_user(
            db_session, phone_number="+14155550030", full_name="Owner1"
        )
        sub1 = await create_test_subscription(
            db_session, owner1, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan1 = await create_test_group_plan(db_session, owner1, sub1)

        owner2 = await create_test_user(
            db_session, phone_number="+14155550031", full_name="Owner2"
        )
        sub2 = await create_test_subscription(
            db_session, owner2, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan2 = await create_test_group_plan(db_session, owner2, sub2)

        joiner = await create_test_user(
            db_session, phone_number="+14155550032", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan1.invite_code, user=joiner
        )

        with pytest.raises(Exception, match="already in a group plan"):
            await group_plan_service.join_plan(
                db_session, invite_code=plan2.invite_code, user=joiner
            )

    async def test_join_plan_rejects_expired(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550040", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value, days_remaining=-1
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550041", full_name="Joiner"
        )
        with pytest.raises(Exception, match="no longer active"):
            await group_plan_service.join_plan(
                db_session, invite_code=plan.invite_code, user=joiner
            )

    async def test_join_plan_rejects_invalid_code(self, db_session: AsyncSession):
        joiner = await create_test_user(
            db_session, phone_number="+14155550042", full_name="Joiner"
        )
        with pytest.raises(Exception, match="not found"):
            await group_plan_service.join_plan(
                db_session, invite_code="badcode", user=joiner
            )

    async def test_remove_member(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550050", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550051", full_name="Joiner"
        )
        member = await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        await group_plan_service.remove_member(
            db_session, group_plan=plan, member_id=member.id, requestor=owner
        )

        updated = await crud_group_plan_member.get(db_session, id=member.id)
        assert updated.left_at is not None

    async def test_remove_member_cannot_remove_owner(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550060", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        members = await crud_group_plan_member.get_active_members(
            db_session, group_plan_id=plan.id
        )
        owner_member = members[0]

        with pytest.raises(Exception, match="Cannot remove plan owner"):
            await group_plan_service.remove_member(
                db_session, group_plan=plan, member_id=owner_member.id, requestor=owner
            )

    async def test_leave_plan(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550070", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550071", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        await group_plan_service.leave_plan(
            db_session, user=joiner, group_plan_id=plan.id
        )

        membership = await crud_group_plan_member.get_active_membership(
            db_session, user_id=joiner.id
        )
        assert membership is None

    async def test_owner_cannot_leave(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550080", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        with pytest.raises(Exception, match="Owner cannot leave"):
            await group_plan_service.leave_plan(
                db_session, user=owner, group_plan_id=plan.id
            )

    async def test_regenerate_invite_code(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550090", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        old_code = plan.invite_code
        new_code = await group_plan_service.regenerate_invite_code(
            db_session, group_plan=plan
        )

        assert new_code != old_code

    async def test_grant_grace_period(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550100", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550101", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        await group_plan_service.grant_grace_period_to_members(db_session, plan, days=7)

        await db_session.refresh(joiner)
        assert joiner.free_credit_end is not None
        assert joiner.free_credit_end > datetime.now(UTC)

        # Owner should NOT get grace period
        await db_session.refresh(owner)
        assert owner.free_credit_end is None

    async def test_access_check_group_plan(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550110", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550111", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        result = await subscription_service.check_access(db_session, joiner)
        assert result.has_access is True
        assert result.reason == "group_plan"
        assert result.group_plan_id == plan.id
        assert result.group_plan_owner_name == "Owner"

    async def test_access_check_expired_group_plan(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550120", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value, days_remaining=-1
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550121", full_name="Joiner"
        )
        # Directly add member since join validates subscription
        from app.models.group_plan import GroupPlanMember

        member = GroupPlanMember(
            group_plan_id=plan.id,
            user_id=joiner.id,
            role=GroupPlanMemberRole.MEMBER.value,
            joined_at=datetime.now(UTC),
        )
        db_session.add(member)
        await db_session.commit()

        result = await subscription_service.check_access(db_session, joiner)
        assert result.reason != "group_plan"

    async def test_direct_subscription_takes_priority(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550130", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550131", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        # Give joiner their own subscription
        await create_test_subscription(
            db_session, joiner, plan_type=PlanType.MONTHLY.value
        )

        result = await subscription_service.check_access(db_session, joiner)
        assert result.reason == "subscription"

    async def test_after_leave_falls_to_next_priority(self, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550140", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550141", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        # Verify access via group plan
        result = await subscription_service.check_access(db_session, joiner)
        assert result.reason == "group_plan"

        # Leave and verify falls back to free trial
        await group_plan_service.leave_plan(
            db_session, user=joiner, group_plan_id=plan.id
        )
        result = await subscription_service.check_access(db_session, joiner)
        assert result.reason == "free_trial"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------
class TestGroupPlanEndpoints:
    async def test_get_no_plan(
        self, client: AsyncClient, test_user: User, auth_headers: dict
    ):
        response = await client.get("/api/v1/groups", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() is None

    async def test_get_as_owner(self, client: AsyncClient, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550200", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        token = create_access_token(str(owner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/groups", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(plan.id)
        assert data["owner_name"] == "Owner"
        assert data["invite_code"] == plan.invite_code
        assert data["member_count"] == 1

    async def test_get_as_member(self, client: AsyncClient, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550210", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550211", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/groups", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(plan.id)
        assert data["member_count"] == 2

    async def test_join_via_invite(self, client: AsyncClient, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550220", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550221", full_name="Joiner"
        )
        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            f"/api/v1/groups/{plan.invite_code}/members", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "member"
        assert data["full_name"] == "Joiner"

    async def test_join_rejects_full_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550230", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await group_plan_service.create_group_plan(
            db_session, owner=owner, subscription_id=sub.id, max_members=1
        )

        joiner = await create_test_user(
            db_session, phone_number="+14155550231", full_name="Joiner"
        )
        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            f"/api/v1/groups/{plan.invite_code}/members", headers=headers
        )
        assert response.status_code == 400
        assert "full" in response.json()["detail"]

    async def test_join_rejects_already_in_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner1 = await create_test_user(
            db_session, phone_number="+14155550240", full_name="O1"
        )
        sub1 = await create_test_subscription(
            db_session, owner1, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan1 = await create_test_group_plan(db_session, owner1, sub1)

        owner2 = await create_test_user(
            db_session, phone_number="+14155550241", full_name="O2"
        )
        sub2 = await create_test_subscription(
            db_session, owner2, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan2 = await create_test_group_plan(db_session, owner2, sub2)

        joiner = await create_test_user(
            db_session, phone_number="+14155550242", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan1.invite_code, user=joiner
        )

        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            f"/api/v1/groups/{plan2.invite_code}/members", headers=headers
        )
        assert response.status_code == 409

    async def test_join_rejects_inactive_plan(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550250", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value, days_remaining=-1
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550251", full_name="Joiner"
        )
        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            f"/api/v1/groups/{plan.invite_code}/members", headers=headers
        )
        assert response.status_code == 400
        assert "no longer active" in response.json()["detail"]

    async def test_leave(self, client: AsyncClient, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550260", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550261", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.delete(
            f"/api/v1/groups/{plan.id}/members/me", headers=headers
        )
        assert response.status_code == 200

    async def test_leave_me_route_is_not_the_generic_member_route(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The literal "me" must hit the leave handler (registered first), not
        fall into /{plan_id}/members/{member_id} and 422 on UUID parsing."""
        owner = await create_test_user(
            db_session, phone_number="+14155550262", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550263", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        token = create_access_token(str(joiner.id))
        response = await client.delete(
            f"/api/v1/groups/{plan.id}/members/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code != 422
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_leave_wrong_plan_is_404_and_membership_kept(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The URL's plan id is enforced: a member of plan A can't leave via
        plan B's URL (and stays in plan A)."""
        owner_a = await create_test_user(
            db_session, phone_number="+14155550264", full_name="Owner A"
        )
        sub_a = await create_test_subscription(
            db_session, owner_a, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan_a = await create_test_group_plan(db_session, owner_a, sub_a)

        owner_b = await create_test_user(
            db_session, phone_number="+14155550265", full_name="Owner B"
        )
        sub_b = await create_test_subscription(
            db_session, owner_b, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan_b = await create_test_group_plan(db_session, owner_b, sub_b)

        joiner = await create_test_user(
            db_session, phone_number="+14155550266", full_name="Joiner"
        )
        member = await group_plan_service.join_plan(
            db_session, invite_code=plan_a.invite_code, user=joiner
        )

        token = create_access_token(str(joiner.id))
        response = await client.delete(
            f"/api/v1/groups/{plan_b.id}/members/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "You're not in this group plan"

        await db_session.refresh(member)
        assert member.left_at is None
        assert member.group_plan_id == plan_a.id

    async def test_owner_cannot_leave(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550270", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        token = create_access_token(str(owner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.delete(
            f"/api/v1/groups/{plan.id}/members/me", headers=headers
        )
        assert response.status_code == 400
        assert "Owner cannot leave" in response.json()["detail"]

    async def test_remove_member(self, client: AsyncClient, db_session: AsyncSession):
        owner = await create_test_user(
            db_session, phone_number="+14155550280", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550281", full_name="Joiner"
        )
        member = await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        token = create_access_token(str(owner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.delete(
            f"/api/v1/groups/{plan.id}/members/{member.id}",
            headers=headers,
        )
        assert response.status_code == 200

    async def test_remove_rejects_non_owner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550290", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550291", full_name="Joiner"
        )
        member = await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        # Try to remove as joiner (not owner)
        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.delete(
            f"/api/v1/groups/{plan.id}/members/{member.id}",
            headers=headers,
        )
        assert response.status_code == 403

    async def test_regenerate_invite(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550300", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        token = create_access_token(str(owner.id))
        headers = {"Authorization": f"Bearer {token}"}

        old_code = plan.invite_code
        response = await client.post(
            f"/api/v1/groups/{plan.id}/invite-code",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["invite_code"] != old_code

    async def test_regenerate_rejects_non_owner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550310", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550311", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            f"/api/v1/groups/{plan.id}/invite-code",
            headers=headers,
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Subscription access integration
# ---------------------------------------------------------------------------
class TestGroupPlanSubscriptionAccess:
    async def test_group_membership_grants_access(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550400", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550401", full_name="Joiner"
        )
        await group_plan_service.join_plan(
            db_session, invite_code=plan.invite_code, user=joiner
        )

        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/subscriptions", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["has_access"] is True
        assert data["reason"] == "group_plan"
        assert data["group_plan_id"] == str(plan.id)
        assert data["group_plan_owner_name"] == "Owner"

    async def test_group_expired_no_access(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155550410", full_name="Owner"
        )
        sub = await create_test_subscription(
            db_session, owner, plan_type=PlanType.GROUP_MONTHLY.value, days_remaining=-1
        )
        plan = await create_test_group_plan(db_session, owner, sub)

        joiner = await create_test_user(
            db_session, phone_number="+14155550411", full_name="Joiner"
        )
        from app.models.group_plan import GroupPlanMember

        member = GroupPlanMember(
            group_plan_id=plan.id,
            user_id=joiner.id,
            role=GroupPlanMemberRole.MEMBER.value,
            joined_at=datetime.now(UTC),
        )
        db_session.add(member)
        await db_session.commit()

        token = create_access_token(str(joiner.id))
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/subscriptions", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["reason"] != "group_plan"
