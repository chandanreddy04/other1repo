"""Sponsorship request endpoint — records gift asks for fulfillment-rate analytics.

Related: app/models/sponsor.py, app/crud/sponsor.py
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import get_current_user_with_profile
from app.api.v1.deps.db import get_db
from app.crud.phone_number import crud_phone_number
from app.crud.sponsor import crud_sponsorship_request
from app.models.sponsor import SponsorshipRequest
from app.models.user import User as UserModel
from app.schemas.sponsor import CreateSponsorshipRequest
from app.utils.phone import format_to_e164

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_sponsorship_request(
    body: CreateSponsorshipRequest,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Record that the user asked someone to gift them a subscription."""
    target_phone_e164 = format_to_e164(body.target_phone)
    if not target_phone_e164:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid phone number",
        )

    target_phone, _ = await crud_phone_number.get_or_create(db, number=target_phone_e164)

    # Idempotent: if there's already a pending request for this pair, don't
    # create a second one (the partial-unique index would reject it anyway).
    existing = await crud_sponsorship_request.get_pending_for_pair(
        db,
        requester_phone_id=current_user.phone_number_id,
        target_phone_id=target_phone.id,
    )
    if existing is None:
        req = SponsorshipRequest(
            requester_phone_id=current_user.phone_number_id,
            target_phone_id=target_phone.id,
        )
        db.add(req)
        await db.commit()

    return Response(status_code=status.HTTP_201_CREATED)
