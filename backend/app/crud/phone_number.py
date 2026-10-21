from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.base import CRUDBase
from app.models.phone_number import PhoneNumber
from app.schemas.user import UserCreate, UserUpdate


class CRUDPhoneNumber(CRUDBase[PhoneNumber, UserCreate, UserUpdate]):
    async def get_by_number(
        self, db: AsyncSession, *, number: str
    ) -> PhoneNumber | None:
        result = await db.execute(
            select(PhoneNumber).where(PhoneNumber.number == number)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, db: AsyncSession, *, number: str
    ) -> tuple[PhoneNumber, bool]:
        """Get existing phone number record or create a new one.

        Returns (phone_number, is_new) tuple.
        """
        existing = await self.get_by_number(db, number=number)
        if existing:
            return existing, False

        db_obj = PhoneNumber(number=number)
        phone = await self._commit_and_refresh(db, db_obj)
        return phone, True

    async def mark_verified(
        self, db: AsyncSession, *, phone: PhoneNumber
    ) -> PhoneNumber:
        phone.verified = True
        return await self._commit_and_refresh(db, phone)


crud_phone_number = CRUDPhoneNumber(PhoneNumber)
