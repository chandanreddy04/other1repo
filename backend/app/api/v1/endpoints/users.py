import logging
from typing import Literal

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import (
    get_current_active_user,
    get_current_user_allow_soft_deleted,
)
from app.api.v1.deps.db import get_db
from app.crud import crud_user
from app.models.user import User as UserModel
from app.schemas.user import User, UserUpdate
from app.services import account_deletion, subscription_service
from app.services.account_deletion import (
    DELETION_GRACE_DAYS,
    GraceExpiredError,
    scheduled_purge_at,
)
from app.services.file_upload import upload_image

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me", response_model=User)
async def get_current_user(
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    stats = await subscription_service.get_referral_stats(db, current_user.id)
    remaining = current_user.max_referral_redemptions - stats["completed_referrals"]
    user_data = User.model_validate(current_user, from_attributes=True)
    user_data.referrals_remaining = remaining
    # Surface SMS opt-out state via the joined phone row so mobile can
    # decide whether to show the "you unsubscribed" banner + management
    # section. The raw timestamp stays server-side; mobile only needs
    # the boolean.
    user_data.sms_unsubscribed = (
        current_user.phone is not None
        and current_user.phone.sms_opted_out_at is not None
    )
    return user_data


@router.put("/me", response_model=User)
async def update_current_user(
    user_update: UserUpdate,
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    user = await crud_user.update(db, db_obj=current_user, obj_in=user_update)
    return user


class DeleteAccountRequest(BaseModel):
    """Optional body for `DELETE /users/me`.

    `sponsorship_choices` maps Stripe subscription IDs that the user is
    currently sponsoring to "stop" (cancel at period end, default) or
    "keep" (leave the Stripe sub running so the user keeps paying after
    their account is gone — managed via phone-keyed sponsorship page).
    Any sub not listed defaults to "stop".
    """

    sponsorship_choices: dict[str, Literal["stop", "keep"]] = Field(
        default_factory=dict
    )


class DeleteAccountResponse(BaseModel):
    """Confirmation that soft-delete succeeded.

    `scheduled_deletion_at` is when the hard-purge worker becomes
    eligible to anonymize the user's PII. Used by mobile to render the
    Welcome Back screen if the user signs back in during grace.
    """

    soft_deleted: bool
    scheduled_deletion_at: str
    grace_days: int


@router.delete("/me", response_model=DeleteAccountResponse)
async def delete_current_user(
    request: DeleteAccountRequest = Body(default_factory=DeleteAccountRequest),
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Initiate account deletion for the authenticated user.

    Soft-deletes immediately and schedules hard-purge for
    now + DELETION_GRACE_DAYS. Stripe subscriptions are cancelled at
    period end. See app/services/account_deletion.py for the full
    orchestration and docs/account-deletion-plan.md for the policy.
    """
    deleted_at = await account_deletion.delete_user_account(
        db, current_user, sponsorship_choices=request.sponsorship_choices
    )
    return DeleteAccountResponse(
        soft_deleted=True,
        scheduled_deletion_at=scheduled_purge_at(deleted_at).isoformat(),
        grace_days=DELETION_GRACE_DAYS,
    )


@router.post("/me/restore", response_model=User)
async def restore_current_user(
    current_user: UserModel = Depends(get_current_user_allow_soft_deleted),
    db: AsyncSession = Depends(get_db),
):
    """Clear soft-delete for the authenticated user, mid-grace.

    Drives the Welcome Back screen on mobile: after OTP verify returns
    `deletion_pending`, the user taps "Restore my account" and we land
    here. Idempotent on already-active users.

    Uses a permissive auth dep (allows soft-deleted users) so the user
    can authenticate with the access_token issued during the verify-otp
    deletion-pending response and then call this endpoint.
    """
    try:
        await account_deletion.restore_user_account(db, current_user)
    except GraceExpiredError as exc:
        # Past the 30-day grace — the row may not be hard-purged yet (the
        # worker tick runs hourly) but policy is fresh user_id on
        # re-signup, not restoration of a stale row. Mobile interprets
        # 410 Gone as "go through new-account signup".
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    return current_user


@router.post("/me/profile-photo", response_model=User)
async def upload_profile_photo(
    file: UploadFile = File(...),
    current_user: UserModel = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload profile photo"""
    url = await upload_image(file, "profile-photos", current_user.id, max_size_mb=5)

    current_user.profile_photo_url = url
    await db.commit()
    await db.refresh(current_user)

    return current_user
