import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import get_current_user_with_profile
from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.crud import crud_circle_of_trust, crud_session, crud_user
from app.crud.phone_number import crud_phone_number
from app.models.circle_of_trust import ContactStatus
from app.models.user import User as UserModel
from app.schemas.circle_of_trust import (
    CircleOfTrustMember,
    CircleOfTrustMemberCreate,
)
from app.utils.phone import format_to_e164


async def _ensure_no_active_session(db: AsyncSession, user_id: UUID) -> None:
    if await crud_session.get_active_session(db, user_id=user_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify your circle while a session is active",
        )


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=list[CircleOfTrustMember])
async def get_trusted_contacts(
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    # is_app_user / contact_full_name / contact_phone are derived model
    # properties (the contact account is looked up from the phone, eager-loaded),
    # so the schema serializes them directly — no manual enrichment needed.
    contacts = await crud_circle_of_trust.get_user_contacts(db, user_id=current_user.id)
    return [
        CircleOfTrustMember.model_validate(c, from_attributes=True) for c in contacts
    ]


@router.post("", response_model=CircleOfTrustMember)
async def add_trusted_contact(
    contact_in: CircleOfTrustMemberCreate,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_no_active_session(db, current_user.id)

    # Contact limit. `get_contact_count` defaults to status=ACTIVE, which
    # excludes OPTED_OUT/PENDING/REMOVED — the semantic is "functional slots".
    contact_count = await crud_circle_of_trust.get_contact_count(
        db, user_id=current_user.id
    )
    if contact_count >= settings.MAX_TRUSTED_CONTACTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Maximum number of Circle members "
                f"({settings.MAX_TRUSTED_CONTACTS}) reached"
            ),
        )

    # A phone number is the contact's identity — always required.
    phone = contact_in.contact_phone_number or contact_in.phone_number
    if not phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A phone number is required to add a contact",
        )
    e164 = format_to_e164(phone) or phone

    # Block a phone that previously opted out of our SMS (the invite would
    # silently fail at Twilio). The structured code lets mobile render the
    # inline "text them yourself" state.
    pn = await crud_phone_number.get_by_number(db, number=e164)
    if pn and pn.sms_opted_out_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "blocked_opt_out", "phone": e164},
        )

    # Whether the contact is an app user is derived from the phone.
    contact_user = await crud_user.get_by_phone(db, phone_number=e164)
    if contact_user and contact_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot add yourself as a Circle member",
        )
    # Non-app contacts have no account name to fall back to, so a nickname is
    # required for them.
    if not contact_user and not contact_in.nickname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A name is required for contacts who aren't app users",
        )

    # One durable row per (owner, contact phone): revive a REMOVED row rather
    # than minting a new identity; reject an active/pending duplicate.
    phone_obj, _ = await crud_phone_number.get_or_create(db, number=e164)
    existing = await crud_circle_of_trust.get_relationship(
        db, user_id=current_user.id, contact_phone_number_id=phone_obj.id
    )
    if existing:
        if existing.status == ContactStatus.REMOVED:
            return await crud_circle_of_trust.revive_to_pending(db, contact=existing)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This contact is already in your Circle",
        )

    contact_in.contact_phone_number = e164
    return await crud_circle_of_trust.create_by_phone(
        db, user_id=current_user.id, obj_in=contact_in
    )


@router.delete("/{member_id}")
async def remove_trusted_contact(
    member_id: UUID,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_no_active_session(db, current_user.id)

    contact = await crud_circle_of_trust.get_owned_or_404(
        db,
        id=member_id,
        owner=current_user,
        resource_name="contact",
        custom_error="You can only remove your own Circle members",
    )

    # Soft remove — keep the row so re-adding revives the same identity.
    await crud_circle_of_trust.soft_set_status(
        db, contact=contact, status=ContactStatus.REMOVED
    )

    return {"detail": "Circle member removed successfully"}
