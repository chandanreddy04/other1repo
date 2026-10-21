import secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.crud.group_plan import crud_group_plan, crud_group_plan_member
from app.models.group_plan import (
    GroupPlan,
    GroupPlanMember,
    GroupPlanMemberRole,
)
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services.subscription_service import apply_referral_credit


async def create_group_plan(
    db: AsyncSession,
    *,
    owner: User,
    subscription_id: UUID,
    max_members: int = 5,
) -> GroupPlan:
    return await crud_group_plan.create_with_owner(
        db, owner=owner, subscription_id=subscription_id, max_members=max_members
    )


async def join_plan(
    db: AsyncSession,
    *,
    invite_code: str,
    user: User,
) -> GroupPlanMember:
    plan = await crud_group_plan.get_by_invite_code(db, code=invite_code)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group plan not found",
        )

    # Check subscription is active
    sub = plan.subscription
    now = datetime.now(UTC)
    if (
        not sub
        or sub.status != SubscriptionStatus.ACTIVE.value
        or sub.current_period_end <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group plan is no longer active",
        )

    # Check user not already in a plan
    existing = await crud_group_plan_member.get_active_membership(db, user_id=user.id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You're already in a group plan",
        )

    # Lock the plan row so two concurrent joins can't both pass the cap check
    # and overflow max_members.
    await db.execute(
        select(GroupPlan.id).where(GroupPlan.id == plan.id).with_for_update()
    )

    # Check plan not full
    count = await crud_group_plan_member.count_active(db, group_plan_id=plan.id)
    if count >= plan.max_members:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group plan is full",
        )

    # Revive a prior (left) membership for this exact plan instead of inserting
    # a second row — that would collide with uq_gpm_plan_user and 500.
    prior = await db.execute(
        select(GroupPlanMember).where(
            GroupPlanMember.group_plan_id == plan.id,
            GroupPlanMember.user_id == user.id,
        )
    )
    member = prior.scalar_one_or_none()
    if member is not None:
        member.left_at = None
        member.joined_at = datetime.now(UTC)
        member.role = GroupPlanMemberRole.MEMBER.value
    else:
        member = GroupPlanMember(
            group_plan_id=plan.id,
            user_id=user.id,
            role=GroupPlanMemberRole.MEMBER.value,
            joined_at=datetime.now(UTC),
        )
        db.add(member)
    return await crud_group_plan_member._commit_and_refresh(db, member)


async def remove_member(
    db: AsyncSession,
    *,
    group_plan: GroupPlan,
    member_id: UUID,
    requestor: User,
) -> None:
    if group_plan.owner_user_id != requestor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the plan owner can remove members",
        )

    member = await crud_group_plan_member.get(db, id=member_id)
    if (
        not member
        or member.group_plan_id != group_plan.id
        or member.left_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    if member.role == GroupPlanMemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove plan owner",
        )

    member.left_at = datetime.now(UTC)
    await db.commit()


async def leave_plan(db: AsyncSession, *, user: User, group_plan_id: UUID) -> None:
    member = await crud_group_plan_member.get_active_membership(db, user_id=user.id)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You're not in a group plan",
        )
    # DELETE /groups/{plan_id}/members/me — the URL names the plan; a caller
    # whose membership is in a different plan must not leave it by accident.
    if member.group_plan_id != group_plan_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You're not in this group plan",
        )

    if member.role == GroupPlanMemberRole.OWNER.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Owner cannot leave. Cancel subscription instead.",
        )

    member.left_at = datetime.now(UTC)
    await db.commit()


async def regenerate_invite_code(db: AsyncSession, *, group_plan: GroupPlan) -> str:
    group_plan.invite_code = secrets.token_urlsafe(16)
    await db.commit()
    await db.refresh(group_plan)
    return group_plan.invite_code


async def grant_grace_period_to_members(
    db: AsyncSession,
    group_plan: GroupPlan,
    days: int = 7,
) -> None:
    from app.crud.notification_delivery import DeliveryDraft
    from app.crud.user import crud_user
    from app.models.notification_delivery import NotificationKind
    from app.services.notification_constants import (
        GROUP_PLAN_GRACE_BODY,
        GROUP_PLAN_GRACE_TITLE,
    )
    from app.services.notification_outbox import build_broadcast_rows, enqueue_and_send

    owner = await crud_user.get(db, id=group_plan.owner_user_id)
    # Only split a REAL full_name — the old code split the fallback phrase
    # too, so a nameless/purged owner rendered as "The" (bug fixed
    # 2026-09-27; the fallback is now the whole phrase, never split).
    owner_first = (
        owner.full_name.split(" ")[0] if owner and owner.full_name else "The owner"
    )

    members = await crud_group_plan_member.get_active_members(
        db, group_plan_id=group_plan.id
    )
    now = datetime.now(UTC)
    # The grace period used to run silently — members just lost access a
    # week later with no explanation (flow-review E3). Routed through the
    # outbox (owner decision: every push auditable): a row gets REFUSED "no
    # push token" for a member without one instead of being silently
    # skipped, and the reconciler retries a transient send failure instead
    # of dropping it. The reconciler resolves the token from the user id.
    # Dedupe key (plan, member) — a re-run for the same plan never re-pushes.
    rows: list[DeliveryDraft] = []
    for member in members:
        if member.role == GroupPlanMemberRole.OWNER.value:
            continue
        await apply_referral_credit(db, member.user_id, days=days)
        rows.extend(
            build_broadcast_rows(
                NotificationKind.GROUP_PLAN_GRACE,
                scope_id=group_plan.id,
                now=now,
                title=GROUP_PLAN_GRACE_TITLE,
                body=GROUP_PLAN_GRACE_BODY.format(owner=owner_first, days=days),
                data={"type": "group_plan_grace"},
                recipient_user_id=member.user_id,
            )
        )
    await enqueue_and_send(db, rows, now=now)


async def get_group_plan_for_access_check(
    db: AsyncSession, user_id: UUID
) -> tuple[Subscription, GroupPlan] | None:
    now = datetime.now(UTC)
    result = await db.execute(
        select(Subscription, GroupPlan)
        .join(GroupPlan, GroupPlan.subscription_id == Subscription.id)
        .join(
            GroupPlanMember,
            GroupPlanMember.group_plan_id == GroupPlan.id,
        )
        .where(
            GroupPlanMember.user_id == user_id,
            GroupPlanMember.left_at.is_(None),
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.current_period_end > now,
        )
        .options(joinedload(GroupPlan.owner))
    )
    row = result.unique().first()
    if row:
        return row[0], row[1]
    return None
