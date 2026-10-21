from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.crud.base import CRUDBase
from app.crud.phone_number import crud_phone_number
from app.models.phone_number import PhoneNumber
from app.models.session import Session, SessionStatus
from app.models.user import STRIPE_CUSTOMER_PENDING_PREFIX, User
from app.schemas.user import UserCreate, UserUpdate


class CRUDUser(CRUDBase[User, UserCreate, UserUpdate]):
    async def get_by_phone(self, db: AsyncSession, *, phone_number: str) -> User | None:
        result = await db.execute(
            select(User)
            .join(PhoneNumber, User.phone_number_id == PhoneNumber.id)
            .where(PhoneNumber.number == phone_number)
            .options(joinedload(User.phone))
        )
        return result.unique().scalar_one_or_none()

    async def create(
        self, db: AsyncSession, *, obj_in: UserCreate, **extra_fields
    ) -> User:
        phone, _ = await crud_phone_number.get_or_create(db, number=obj_in.phone_number)
        db_obj = User(
            phone_number_id=phone.id,
            full_name=obj_in.full_name,
            profile_photo_url=obj_in.profile_photo_url,
            stripe_customer_id=extra_fields.pop("stripe_customer_id", f"{STRIPE_CUSTOMER_PENDING_PREFIX}{phone.id}"),
            **extra_fields,
        )
        return await self._commit_and_refresh(db, db_obj)

    async def get_or_create_by_phone(
        self, db: AsyncSession, *, phone_number: str, **extra_fields
    ) -> tuple[User, bool]:
        """Get existing user by phone or create a new one.

        Returns (user, is_new_user) tuple.
        """
        user = await self.get_by_phone(db, phone_number=phone_number)
        if user:
            return user, False

        phone, _ = await crud_phone_number.get_or_create(db, number=phone_number)
        db_obj = User(
            phone_number_id=phone.id,
            phone_ownership_verified=True,
            stripe_customer_id=extra_fields.pop("stripe_customer_id", f"{STRIPE_CUSTOMER_PENDING_PREFIX}{phone.id}"),
            **extra_fields,
        )
        user = await self._commit_and_refresh(db, db_obj)
        return user, True

    async def get_by_share_code(
        self, db: AsyncSession, *, share_code: str
    ) -> User | None:
        result = await db.execute(
            select(User)
            .where(User.share_code == share_code.upper())
            .options(joinedload(User.phone))
        )
        return result.scalar_one_or_none()

    async def get_by_circle_invite_code(
        self, db: AsyncSession, *, circle_invite_code: str
    ) -> User | None:
        result = await db.execute(
            select(User).where(
                User.circle_invite_code == circle_invite_code.upper()
            )
        )
        return result.scalar_one_or_none()

    def is_active(self, user: User) -> bool:
        return user.is_active

    async def get_purge_eligible(
        self, db: AsyncSession, *, cutoff: datetime
    ) -> list[User]:
        """Soft-deleted users past grace and with no in-flight sessions.

        `cutoff` must be a tz-aware UTC datetime; it's compared against
        `deleted_at` (also tz-aware UTC). Pass `datetime.now(UTC) -
        timedelta(days=DELETION_GRACE_DAYS)`.

        A user is eligible for hard-purge when:
        - `deleted_at < cutoff` (grace expired), and
        - they have no Session in ACTIVE / MISSED / ALERTED status
          (any non-terminal session — completing it sends an
          all-clear, so a hanging in-flight session must resolve
          before we anonymize the owner's PII).

        Uses the `ix_users_deleted_at` partial index for the
        `deleted_at IS NOT NULL` predicate; the `< cutoff` predicate
        then filters down to past-grace rows, so the scan is
        O(soft-deleted) rather than O(total users). Soft-deleted users
        race against creating new sessions because is_active=False
        rejects auth — so the no-in-flight-sessions check captures
        every session that could possibly belong to the row.
        """
        in_flight = {
            SessionStatus.ACTIVE,
            SessionStatus.MISSED,
            SessionStatus.ALERTED,
        }
        result = await db.execute(
            select(User).where(
                User.deleted_at.is_not(None),
                User.deleted_at < cutoff,
                ~exists().where(
                    Session.user_id == User.id,
                    Session.status.in_(in_flight),
                ),
            )
        )
        return list(result.scalars().all())


crud_user = CRUDUser(User)
