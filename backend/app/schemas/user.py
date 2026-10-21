from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.photo_urls import to_viewable_url


class UserBase(BaseModel):
    phone_number: str = Field(
        ..., pattern="^\\+[1-9]\\d{1,14}$"
    )  # E164 format required
    full_name: str | None = Field(None, min_length=1, max_length=100)
    profile_photo_url: str | None = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone_e164(cls, v):
        """Ensure phone number is in E164 format"""
        if not v.startswith("+"):
            raise ValueError("Phone number must be in E164 format (starting with +)")
        # Remove any non-digit characters except the leading +
        cleaned = "+" + "".join(filter(str.isdigit, v[1:]))
        if len(cleaned) < 10 or len(cleaned) > 16:
            raise ValueError("Phone number must be between 10 and 15 digits")
        return cleaned


class UserCreate(UserBase):
    """Used for creating new users via OTP - no password needed"""

    pass


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=100)
    profile_photo_url: str | None = None
    # Phone number cannot be updated directly - would require OTP verification


class UserInDBBase(UserBase):
    id: UUID
    is_active: bool
    phone_ownership_verified: bool
    share_code: str | None = None
    circle_invite_code: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _sign_profile_photo(self):
        # Raw private-S3 avatar URL → viewable presigned URL. See photo_urls.py.
        self.profile_photo_url = to_viewable_url(self.profile_photo_url)
        return self


class User(UserInDBBase):
    """User model returned to clients"""

    referrals_remaining: int | None = None
    # True when the user's own phone has texted STOP to our Twilio
    # number. Mobile shows a management surface (banner + profile
    # section) when this is set so they can re-enable texts, cancel
    # their subscription explicitly, or wait for the worker to act
    # after the grace window. See app/services/sms_unsubscribe_tasks.
    sms_unsubscribed: bool = False
