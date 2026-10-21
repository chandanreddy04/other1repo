import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import get_current_user_with_profile
from app.api.v1.deps.db import get_db
from app.crud import crud_circle_of_trust_settings
from app.models.user import User as UserModel
from app.schemas.circle_of_trust import (
    CircleOfTrustSettings,
    CircleOfTrustSettingsUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/settings", response_model=CircleOfTrustSettings)
async def get_circle_of_trust_settings(
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    """Get Circle of Trust settings for the current user"""
    settings = await crud_circle_of_trust_settings.get_or_create_settings(
        db, user_id=current_user.id
    )
    return settings


@router.put("/settings", response_model=CircleOfTrustSettings)
async def update_circle_of_trust_settings(
    settings_update: CircleOfTrustSettingsUpdate,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    """Update Circle of Trust settings for the current user"""
    settings = await crud_circle_of_trust_settings.update_settings(
        db, user_id=current_user.id, obj_in=settings_update
    )
    return settings
