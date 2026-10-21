import logging
import secrets
import string
from datetime import UTC, datetime

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.account_grant import crud_account_grant
from app.models.otp import OTP
from app.services.sms import sms_service
from app.utils.phone import format_to_e164

logger = logging.getLogger(__name__)


class OTPService:
    def __init__(self):
        self.otp_length = 6
        self.expiry_minutes = 15  # OTP valid for 15 minutes
        self.max_attempts = 3
        self.resend_delay_seconds = 60

    def generate_otp_code(self) -> str:
        """Generate a random 6-digit OTP code"""
        return "".join(secrets.choice(string.digits) for _ in range(self.otp_length))

    async def send_otp(
        self, db: AsyncSession, phone_number: str, force_resend: bool = False
    ) -> tuple[bool, str]:
        """
        Send OTP to phone number
        Returns (success, message)
        """
        try:
            # Format phone number to E164 using phonenumbers library
            clean_phone = format_to_e164(phone_number)
            if not clean_phone:
                return False, "Invalid phone number format"

            # Managed-account bypass: an admin-configured AccountGrant with a
            # fixed login code (store reviewers who can't receive SMS) gets that
            # code stored and NO SMS sent — the code is never logged. verify_otp
            # validates it through the normal path. Grants without a code (or no
            # grant at all) fall through to standard OTP.
            grant = await crud_account_grant.get_enabled_by_phone(
                db, phone_number=clean_phone
            )
            if grant and grant.otp_code:
                await self._expire_active_otps(db, clean_phone)
                otp = OTP(
                    phone_number=clean_phone,
                    otp_code=grant.otp_code,
                    expires_in_minutes=self.expiry_minutes,
                )
                db.add(otp)
                await db.commit()
                return True, "Verification code sent to your phone"

            # Check for recent active OTP (prevent spam)
            if not force_resend:
                active_otp = await self.get_active_otp(db, clean_phone)
                if active_otp:
                    time_since = (
                        datetime.now(UTC) - active_otp.created_at
                    ).total_seconds()
                    if time_since < self.resend_delay_seconds:
                        wait_time = int(self.resend_delay_seconds - time_since)
                        return (
                            False,
                            f"Please wait {wait_time} seconds before requesting a new code",
                        )

            # Expire any existing unused OTPs for this phone number
            await self._expire_active_otps(db, clean_phone)

            # Generate new OTP
            otp_code = self.generate_otp_code()

            # Save to database
            otp = OTP(
                phone_number=clean_phone,
                otp_code=otp_code,
                expires_in_minutes=self.expiry_minutes,
            )
            db.add(otp)
            await db.commit()

            if settings.ENVIRONMENT == "development":
                logger.info("OTP for %s: %s", clean_phone, otp_code)
                print(f"\n📱 OTP CODE FOR {clean_phone}: {otp_code}\n")
                return True, "Verification code sent (check console in dev mode)"
            else:
                message = f"Made It Home: Your verification code is {otp_code}\n\nIt expires in 15 minutes."
                result = await sms_service.send_sms(clean_phone, message)
                if result.success:
                    return True, "Verification code sent to your phone"
                else:
                    return False, "Failed to send verification code. Please try again."

        except Exception:
            logger.exception("Error sending OTP")
            return False, "An error occurred. Please try again."

    async def verify_otp(
        self, db: AsyncSession, phone_number: str, otp_code: str
    ) -> tuple[bool, str]:
        """
        Verify OTP code
        Returns (success, message)
        """
        try:
            # Format phone number to E164 using phonenumbers library
            clean_phone = format_to_e164(phone_number)
            if not clean_phone:
                return False, "Invalid phone number format"

            clean_code = otp_code.strip()

            # Get the most recent valid OTP for this phone
            otp = await self.get_active_otp(db, clean_phone)

            if not otp:
                return False, "Invalid or expired verification code"

            # Increment attempts
            otp.attempts += 1

            # Check if too many attempts
            if otp.attempts > self.max_attempts:
                otp.is_used = True
                await db.commit()
                return False, "Too many attempts. Please request a new code."

            # Verify the code
            if not secrets.compare_digest(otp.otp_code, clean_code):
                await db.commit()
                attempts_left = self.max_attempts - otp.attempts
                return False, f"Invalid code. {attempts_left} attempts remaining."

            # Mark as verified and used
            otp.is_verified = True
            otp.is_used = True
            otp.verified_at = datetime.now(UTC)
            await db.commit()

            return True, "Phone number verified successfully"

        except Exception:
            logger.exception("Error verifying OTP")
            return False, "An error occurred during verification"

    async def _expire_active_otps(self, db: AsyncSession, phone_number: str) -> None:
        """Expire all active OTPs for a phone number."""
        query = select(OTP).where(
            and_(
                OTP.phone_number == phone_number,
                OTP.is_used.is_(False),
                OTP.expires_at > datetime.now(UTC),
            )
        )
        result = await db.execute(query)
        for otp in result.scalars().all():
            otp.expires_at = datetime.now(UTC)

    async def get_resend_wait_seconds(self, db: AsyncSession, phone_number: str) -> int:
        """Calculate seconds remaining before resend is allowed. Returns 0 if resend is available."""
        active_otp = await self.get_active_otp(db, phone_number)
        if active_otp:
            time_since = (datetime.now(UTC) - active_otp.created_at).total_seconds()
            if time_since < self.resend_delay_seconds:
                return int(self.resend_delay_seconds - time_since)
        return 0

    async def get_active_otp(self, db: AsyncSession, phone_number: str) -> OTP | None:
        """Get the most recent active (unused, non-expired) OTP for a phone number"""
        query = (
            select(OTP)
            .where(
                and_(
                    OTP.phone_number == phone_number,
                    OTP.is_used.is_(False),
                    OTP.expires_at > datetime.now(UTC),
                )
            )
            .order_by(desc(OTP.created_at))
            .limit(1)
        )

        result = await db.execute(query)
        return result.scalar_one_or_none()


# Create singleton instance
otp_service = OTPService()
