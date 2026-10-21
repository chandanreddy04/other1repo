from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.circle_of_trust_settings import CircleOfTrustSettings
from app.schemas.circle_of_trust import (
    CircleOfTrustSettingsCreate,
    CircleOfTrustSettingsUpdate,
)


class CRUDCircleOfTrustSettings(
    CRUDBase[
        CircleOfTrustSettings, CircleOfTrustSettingsCreate, CircleOfTrustSettingsUpdate
    ]
):
    async def get_by_user_id(
        self, db: AsyncSession, *, user_id: UUID
    ) -> CircleOfTrustSettings | None:
        """Get Circle of Trust settings for a user"""
        result = await db.execute(
            select(CircleOfTrustSettings).where(
                CircleOfTrustSettings.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_settings(
        self, db: AsyncSession, *, user_id: UUID
    ) -> CircleOfTrustSettings:
        """Get existing settings or create default ones"""
        return await self.get_or_create_by_owner(
            db,
            owner_id=user_id,
            defaults={
                "auto_import_contacts": False,
                "sms_invitations_enabled": True,
                "notification_preferences": {},
            },
        )

    async def update_settings(
        self, db: AsyncSession, *, user_id: UUID, obj_in: CircleOfTrustSettingsUpdate
    ) -> CircleOfTrustSettings:
        """Update Circle of Trust settings"""
        settings = await self.get_or_create_settings(db, user_id=user_id)

        update_data = obj_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(settings, field, value)

        return await self._commit_and_refresh(db, settings)


crud_circle_of_trust_settings = CRUDCircleOfTrustSettings(CircleOfTrustSettings)
