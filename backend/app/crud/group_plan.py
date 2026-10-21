import secrets
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.crud.base import CRUDBase
from app.models.group_plan import (
    GroupPlan,
    GroupPlanMember,
    GroupPlanMemberRole,
)
from app.models.user import User


class CRUDGroupPlan(CRUDBase[GroupPlan, BaseModel, BaseModel]):
    async def get_by_owner(
        self, db: AsyncSession, *, owner_user_id: uuid.UUID
    ) -> GroupPlan | None:
        result = await db.execute(
            select(GroupPlan)
            .where(GroupPlan.owner_user_id == owner_user_id)
            .options(joinedload(GroupPlan.owner))
        )
        return result.unique().scalar_one_or_none()

    async def get_by_subscription(
        self, db: AsyncSession, *, subscription_id: uuid.UUID
    ) -> GroupPlan | None:
        result = await db.execute(
            select(GroupPlan)
            .where(GroupPlan.subscription_id == subscription_id)
            .options(joinedload(GroupPlan.owner))
        )
        return result.unique().scalar_one_or_none()

    async def get_by_invite_code(
        self, db: AsyncSession, *, code: str
    ) -> GroupPlan | None:
        result = await db.execute(
            select(GroupPlan)
            .where(GroupPlan.invite_code == code)
            .options(
                joinedload(GroupPlan.owner),
                joinedload(GroupPlan.subscription),
            )
        )
        return result.unique().scalar_one_or_none()

    async def get_user_group_plan(
        self, db: AsyncSession, *, user_id: uuid.UUID
    ) -> tuple[GroupPlan | None, GroupPlanMember | None]:
        """Returns (plan, member) where user is an active member (left_at IS NULL)."""
        result = await db.execute(
            select(GroupPlanMember)
            .where(
                GroupPlanMember.user_id == user_id,
                GroupPlanMember.left_at.is_(None),
            )
            .options(
                joinedload(GroupPlanMember.group_plan).joinedload(GroupPlan.owner),
            )
        )
        member = result.unique().scalar_one_or_none()
        if member:
            return member.group_plan, member
        return None, None

    async def create_with_owner(
        self,
        db: AsyncSession,
        *,
        owner: User,
        subscription_id: uuid.UUID,
        max_members: int = 5,
    ) -> GroupPlan:
        plan = GroupPlan(
            owner_user_id=owner.id,
            subscription_id=subscription_id,
            invite_code=secrets.token_urlsafe(16),
            max_members=max_members,
        )
        plan = await self._commit_and_refresh(db, plan)

        owner_member = GroupPlanMember(
            group_plan_id=plan.id,
            user_id=owner.id,
            role=GroupPlanMemberRole.OWNER.value,
            joined_at=datetime.now(UTC),
        )
        await self._commit_and_refresh(db, owner_member)

        return plan


class CRUDGroupPlanMember(CRUDBase[GroupPlanMember, BaseModel, BaseModel]):
    async def get_active_membership(
        self, db: AsyncSession, *, user_id: uuid.UUID
    ) -> GroupPlanMember | None:
        result = await db.execute(
            select(GroupPlanMember).where(
                GroupPlanMember.user_id == user_id,
                GroupPlanMember.left_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_members(
        self, db: AsyncSession, *, group_plan_id: uuid.UUID
    ) -> list[GroupPlanMember]:
        result = await db.execute(
            select(GroupPlanMember)
            .where(
                GroupPlanMember.group_plan_id == group_plan_id,
                GroupPlanMember.left_at.is_(None),
            )
            .options(joinedload(GroupPlanMember.user))
        )
        return list(result.unique().scalars().all())

    async def count_active(
        self, db: AsyncSession, *, group_plan_id: uuid.UUID
    ) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(GroupPlanMember)
            .where(
                GroupPlanMember.group_plan_id == group_plan_id,
                GroupPlanMember.left_at.is_(None),
            )
        )
        return result.scalar() or 0


crud_group_plan = CRUDGroupPlan(GroupPlan)
crud_group_plan_member = CRUDGroupPlanMember(GroupPlanMember)
