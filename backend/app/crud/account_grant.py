"""CRUD for AccountGrant — resolve admin-managed access grants by phone.

Read-only helper used on the OTP/login hot path (services/otp.py,
api/v1/endpoints/auth.py). Admin create/edit goes through the generic
AdminModelView, so no create/update schema is needed here.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account_grant import AccountGrant
from app.models.phone_number import PhoneNumber


class CRUDAccountGrant:
    async def get_enabled_by_phone(
        self, db: AsyncSession, *, phone_number: str
    ) -> AccountGrant | None:
        """Return the enabled grant for an E164 phone number, or None."""
        result = await db.execute(
            select(AccountGrant)
            .join(PhoneNumber, AccountGrant.phone_number_id == PhoneNumber.id)
            .where(
                PhoneNumber.number == phone_number,
                AccountGrant.enabled.is_(True),
            )
        )
        return result.scalars().first()


crud_account_grant = CRUDAccountGrant()
