"""CRUD for SponsorshipRequest.

Related: app/models/sponsor.py, app/api/v1/endpoints/sponsorship_requests.py
"""

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.sponsor import SponsorshipRequest, SponsorshipRequestStatus


class CRUDSponsorshipRequest(CRUDBase[SponsorshipRequest, BaseModel, BaseModel]):
    async def get_pending_for_pair(
        self,
        db: AsyncSession,
        *,
        requester_phone_id: uuid.UUID,
        target_phone_id: uuid.UUID,
    ) -> SponsorshipRequest | None:
        result = await db.execute(
            select(SponsorshipRequest).where(
                SponsorshipRequest.requester_phone_id == requester_phone_id,
                SponsorshipRequest.target_phone_id == target_phone_id,
                SponsorshipRequest.status == SponsorshipRequestStatus.PENDING.value,
            )
        )
        return result.scalar_one_or_none()

    async def fulfill(
        self,
        db: AsyncSession,
        *,
        request: SponsorshipRequest,
        subscription_id: uuid.UUID,
    ) -> SponsorshipRequest:
        request.status = SponsorshipRequestStatus.FULFILLED.value
        request.fulfilled_at = datetime.now(UTC)
        request.subscription_id = subscription_id
        return await self._commit_and_refresh(db, request)


crud_sponsorship_request = CRUDSponsorshipRequest(SponsorshipRequest)
