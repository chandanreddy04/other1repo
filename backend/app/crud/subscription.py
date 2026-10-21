import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.subscription import (
    Promotion,
    Referral,
    Subscription,
    SubscriptionStatus,
)


class CRUDSubscription(CRUDBase[Subscription, BaseModel, BaseModel]):
    async def get_active_gifted_by_phone(
        self, db: AsyncSession, *, gifter_phone_id: uuid.UUID
    ) -> list[Subscription]:
        """Active subscriptions where the given phone is the gifter.

        Used by account-deletion and any future "manage who I'm sponsoring"
        surface. Phone-keyed (not user-keyed) so it keeps working after the
        gifter's account is soft-deleted/purged.
        """
        result = await db.execute(
            select(Subscription).where(
                Subscription.gifted_by_phone_id == gifter_phone_id,
                Subscription.status == SubscriptionStatus.ACTIVE.value,
            )
        )
        return list(result.scalars().all())


class CRUDReferral(CRUDBase[Referral, BaseModel, BaseModel]):
    pass


class CRUDPromotion(CRUDBase[Promotion, BaseModel, BaseModel]):
    pass


crud_subscription = CRUDSubscription(Subscription)
crud_referral = CRUDReferral(Referral)
crud_promotion = CRUDPromotion(Promotion)
