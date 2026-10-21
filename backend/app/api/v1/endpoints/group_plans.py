from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import get_current_user_with_profile
from app.api.v1.deps.db import get_db
from app.crud.group_plan import crud_group_plan, crud_group_plan_member
from app.models.user import User
from app.schemas.group_plan import GroupPlanMemberResponse, GroupPlanResponse
from app.services import group_plan_service

router = APIRouter()


def _build_response(plan, members) -> GroupPlanResponse:
    return GroupPlanResponse(
        id=plan.id,
        owner_user_id=plan.owner_user_id,
        owner_name=plan.owner.full_name if plan.owner else None,
        invite_code=plan.invite_code,
        max_members=plan.max_members,
        member_count=len(members),
        members=[
            GroupPlanMemberResponse(
                id=m.id,
                user_id=m.user_id,
                full_name=m.user.full_name if m.user else None,
                role=m.role,
                joined_at=m.joined_at,
            )
            for m in members
        ],
        created_at=plan.created_at,
    )


@router.get("")
async def get_group_plan(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_with_profile),
) -> GroupPlanResponse | None:
    plan, _member = await crud_group_plan.get_user_group_plan(
        db, user_id=current_user.id
    )
    if not plan:
        return None

    members = await crud_group_plan_member.get_active_members(db, group_plan_id=plan.id)
    return _build_response(plan, members)


# Joining creates a membership — POST to the members sub-resource collection.
@router.post("/{invite_code}/members")
async def join_group_plan(
    invite_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_with_profile),
) -> GroupPlanMemberResponse:
    """Join a group plan via its shared invite code.

    Path convention: the segment after /groups/ is the INVITE CODE here —
    joining is only possible via the shared code, and the joiner doesn't know
    the plan id yet. Every other /groups/{...} route takes the plan id.
    """
    member = await group_plan_service.join_plan(
        db, invite_code=invite_code, user=current_user
    )
    return GroupPlanMemberResponse(
        id=member.id,
        user_id=member.user_id,
        full_name=current_user.full_name,
        role=member.role,
        joined_at=member.joined_at,
    )


# Leaving deletes the caller's own membership. Registered before the
# generic "/{plan_id}/members/{member_id}" route below so the literal "me"
# segment matches first (Starlette resolves routes in registration order).
@router.delete("/{plan_id}/members/me")
async def leave_group_plan(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_with_profile),
) -> dict:
    await group_plan_service.leave_plan(db, user=current_user, group_plan_id=plan_id)
    return {"status": "ok"}


@router.delete("/{plan_id}/members/{member_id}")
async def remove_group_member(
    plan_id: UUID,
    member_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_with_profile),
) -> dict:
    plan = await crud_group_plan.get(db, id=plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group plan not found",
        )
    await group_plan_service.remove_member(
        db, group_plan=plan, member_id=member_id, requestor=current_user
    )
    return {"status": "ok"}


# Regenerating the invite code creates a new sub-resource value (invalidates
# the old link) — POST to the singular sub-resource, no verb in the path.
@router.post("/{plan_id}/invite-code")
async def regenerate_invite(
    plan_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user_with_profile),
) -> dict:
    plan = await crud_group_plan.get(db, id=plan_id)
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group plan not found",
        )
    if plan.owner_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the plan owner can regenerate the invite code",
        )
    new_code = await group_plan_service.regenerate_invite_code(db, group_plan=plan)
    return {"invite_code": new_code}
