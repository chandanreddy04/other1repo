from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.crud.base import CRUDBase
from app.crud.phone_number import crud_phone_number
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.schemas.circle_of_trust import (
    CircleOfTrustMemberCreate,
    CircleOfTrustMemberUpdate,
)

# "Not currently in the circle" — excluded from active/pending views. The row
# survives (identity is the phone) so re-adding revives it.
_TERMINAL_STATUSES = (ContactStatus.REMOVED,)


def _phone_id_of(user_id: UUID):
    """Scalar subquery for the phone_number_id owned by `user_id`."""
    return select(User.phone_number_id).where(User.id == user_id).scalar_subquery()


class CRUDCircleOfTrust(
    CRUDBase[CircleOfTrustMember, CircleOfTrustMemberCreate, CircleOfTrustMemberUpdate]
):
    async def get_user_contacts(
        self, db: AsyncSession, *, user_id: UUID, status: ContactStatus | None = None
    ) -> list[CircleOfTrustMember]:
        # contact_user is lazy="joined" (eager) so the alert-dispatch worker can
        # read member.contact_user.expo_push_token in an async context without a
        # cold lazy load raising MissingGreenlet.
        query = select(CircleOfTrustMember).where(
            CircleOfTrustMember.user_id == user_id
        )
        if status is not None:
            query = query.where(CircleOfTrustMember.status == status)
        else:
            query = query.where(CircleOfTrustMember.status.notin_(_TERMINAL_STATUSES))

        result = await db.execute(query)
        return result.scalars().all()

    async def get_pending_invitations_for_user(
        self, db: AsyncSession, *, user_id: UUID
    ) -> list[CircleOfTrustMember]:
        """Pending invitations addressed to this user — matched by their phone,
        so invites created before they signed up appear with no linking step."""
        result = await db.execute(
            select(CircleOfTrustMember)
            .where(
                and_(
                    CircleOfTrustMember.contact_phone_number_id == _phone_id_of(user_id),
                    CircleOfTrustMember.status == ContactStatus.PENDING,
                )
            )
            .order_by(CircleOfTrustMember.created_at.desc())
        )
        return result.scalars().all()

    async def get_memberships_for_user(
        self, db: AsyncSession, *, user_id: UUID
    ) -> list[CircleOfTrustMember]:
        """Circles where this user is a member (pending + active), by phone."""
        result = await db.execute(
            select(CircleOfTrustMember)
            .where(
                and_(
                    CircleOfTrustMember.contact_phone_number_id == _phone_id_of(user_id),
                    CircleOfTrustMember.status.in_(
                        [ContactStatus.PENDING, ContactStatus.ACTIVE]
                    ),
                )
            )
            .order_by(CircleOfTrustMember.status, CircleOfTrustMember.created_at.desc())
        )
        return result.scalars().all()

    async def get_contact_count(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        status: ContactStatus = ContactStatus.ACTIVE,
    ) -> int:
        result = await db.execute(
            select(func.count(CircleOfTrustMember.id)).where(
                and_(
                    CircleOfTrustMember.user_id == user_id,
                    CircleOfTrustMember.status == status,
                )
            )
        )
        return result.scalar()

    async def get_relationship(
        self, db: AsyncSession, *, user_id: UUID, contact_phone_number_id: UUID
    ) -> CircleOfTrustMember | None:
        """The single row for this (inviter, contact phone) pair, any status."""
        result = await db.execute(
            select(CircleOfTrustMember).where(
                and_(
                    CircleOfTrustMember.user_id == user_id,
                    CircleOfTrustMember.contact_phone_number_id
                    == contact_phone_number_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_pending_by_pair(
        self, db: AsyncSession, *, inviter_id: UUID, accepter_id: UUID
    ) -> CircleOfTrustMember | None:
        """The inviter's PENDING row for the accepter (matched by accepter's phone)."""
        result = await db.execute(
            select(CircleOfTrustMember).where(
                and_(
                    CircleOfTrustMember.user_id == inviter_id,
                    CircleOfTrustMember.contact_phone_number_id
                    == _phone_id_of(accepter_id),
                    CircleOfTrustMember.status == ContactStatus.PENDING,
                )
            )
        )
        return result.scalar_one_or_none()

    async def create_by_phone(
        self, db: AsyncSession, *, user_id: UUID, obj_in: CircleOfTrustMemberCreate
    ) -> CircleOfTrustMember:
        """Create a relationship keyed by the contact's phone (the only path).

        Whether the contact is an app user is derived from the phone, not stored.
        """
        phone, _ = await crud_phone_number.get_or_create(
            db, number=obj_in.contact_phone_number
        )
        db_obj = CircleOfTrustMember(
            user_id=user_id,
            contact_phone_number_id=phone.id,
            nickname=obj_in.nickname,
            phone_contact_id=obj_in.phone_contact_id,
            status=ContactStatus.PENDING,
            invited_at=datetime.now(UTC),
        )
        return await self._commit_and_refresh(db, db_obj)

    async def accept_invitation(
        self, db: AsyncSession, *, contact: CircleOfTrustMember
    ) -> CircleOfTrustMember:
        contact.status = ContactStatus.ACTIVE
        contact.accepted_at = datetime.now(UTC)
        contact.removed_at = None
        return await self._commit_and_refresh(db, contact)

    async def soft_set_status(
        self, db: AsyncSession, *, contact: CircleOfTrustMember, status: ContactStatus
    ) -> CircleOfTrustMember:
        """Flip lifecycle state in place instead of deleting the row."""
        contact.status = status
        now = datetime.now(UTC)
        if status == ContactStatus.REMOVED:
            contact.removed_at = now
        elif status == ContactStatus.OPTED_OUT:
            contact.opted_out_at = now
        return await self._commit_and_refresh(db, contact)

    async def revive_to_pending(
        self, db: AsyncSession, *, contact: CircleOfTrustMember
    ) -> CircleOfTrustMember:
        """Re-inviting a REMOVED contact reuses the same row (stable identity)."""
        contact.status = ContactStatus.PENDING
        contact.removed_at = None
        contact.invited_at = datetime.now(UTC)
        return await self._commit_and_refresh(db, contact)

    async def get_alerts_contacts(
        self, db: AsyncSession, *, user_id: UUID
    ) -> list[User]:
        """Active app-user contacts for the user — the owning account per phone."""
        result = await db.execute(
            select(User)
            .join(
                CircleOfTrustMember,
                and_(
                    CircleOfTrustMember.contact_phone_number_id == User.phone_number_id,
                    User.deleted_at.is_(None),
                ),
            )
            .where(
                and_(
                    CircleOfTrustMember.user_id == user_id,
                    CircleOfTrustMember.status == ContactStatus.ACTIVE,
                )
            )
            .order_by(CircleOfTrustMember.created_at)
        )
        return result.scalars().all()

    async def get_by_phone_or_contact_id(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        phone_number: str,
        phone_contact_id: str,
    ) -> CircleOfTrustMember | None:
        """Dedup lookup by phone number or device contact id (any status)."""
        result = await db.execute(
            select(CircleOfTrustMember)
            .outerjoin(
                PhoneNumber,
                CircleOfTrustMember.contact_phone_number_id == PhoneNumber.id,
            )
            .where(
                and_(
                    CircleOfTrustMember.user_id == user_id,
                    or_(
                        PhoneNumber.number == phone_number,
                        CircleOfTrustMember.phone_contact_id == phone_contact_id,
                    ),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_non_app_contacts(
        self, db: AsyncSession, *, user_id: UUID
    ) -> list[CircleOfTrustMember]:
        """Contacts with no active app account (SMS-only targets)."""
        owner = aliased(User)
        result = await db.execute(
            select(CircleOfTrustMember)
            .outerjoin(
                owner,
                and_(
                    owner.phone_number_id == CircleOfTrustMember.contact_phone_number_id,
                    owner.deleted_at.is_(None),
                ),
            )
            .where(
                and_(
                    CircleOfTrustMember.user_id == user_id,
                    owner.id.is_(None),
                    CircleOfTrustMember.status.notin_(_TERMINAL_STATUSES),
                )
            )
        )
        return result.scalars().all()


crud_circle_of_trust = CRUDCircleOfTrust(CircleOfTrustMember)
