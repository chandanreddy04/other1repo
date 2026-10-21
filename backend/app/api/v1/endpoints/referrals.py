import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import get_current_user_with_profile
from app.api.v1.deps.db import get_db
from app.crud.user import crud_user
from app.models.user import User as UserModel
from app.schemas.subscription import ApplyReferralRequest, ReferralInfoResponse
from app.services import subscription_service
from app.services.referral import referral_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=ReferralInfoResponse)
async def get_referral_info(
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    # Generate referral code if user doesn't have one
    if not current_user.share_code:
        current_user.share_code = subscription_service.generate_share_code()
        await db.commit()
        await db.refresh(current_user)

    stats = await subscription_service.get_referral_stats(db, current_user.id)
    completed = stats["completed_referrals"]
    return ReferralInfoResponse(
        referral_code=current_user.share_code,
        can_refer=completed < current_user.max_referral_redemptions,
        referrals_used=completed,
        referrals_max=current_user.max_referral_redemptions,
    )


@router.post("")
async def apply_referral(
    body: ApplyReferralRequest,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    code = body.referral_code.upper()

    # Find referrer by code
    referrer = await crud_user.get_by_share_code(db, share_code=code)

    if not referrer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid referral code",
        )

    if referrer.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot use your own referral code",
        )

    if await referral_service.has_existing_referral(db, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already used a referral code",
        )

    await referral_service.claim_referral(db, referrer, current_user, code)

    return {
        "message": "Referral applied. You received 30 days free."
    }


@router.get("/{code}")
async def lookup_referral_code(
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Look up referrer name by referral code (public, for web landing page)"""
    referrer = await crud_user.get_by_share_code(db, share_code=code)
    if not referrer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid referral code",
        )
    first_name = (referrer.full_name or "A friend").split(" ")[0]
    return {"referrer_name": first_name, "referral_code": code.upper()}
