from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.circle_of_trust import ContactStatus


class CircleOfTrustMemberCreate(BaseModel):
    email: str | None = None
    phone_number: str | None = Field(None, pattern="^\\+?[1-9]\\d{1,14}$")

    # The inviter's label for the contact (optional in DB; UX may require it for
    # non-app contacts, who have no account name to fall back to).
    nickname: str | None = None
    contact_phone_number: str | None = Field(None, pattern="^\\+?[1-9]\\d{1,14}$")
    phone_contact_id: str | None = None


class CircleOfTrustMemberUpdate(BaseModel):
    status: ContactStatus | None = None
    nickname: str | None = None
    contact_phone_number: str | None = None
    phone_contact_id: str | None = None
    sms_invitation_sent: bool | None = None
    sms_invitation_sent_at: datetime | None = None
    sms_message_id: str | None = None
    last_nudged_at: datetime | None = None


class CircleOfTrustMember(BaseModel):
    id: UUID
    user_id: UUID
    status: ContactStatus
    invited_at: datetime | None
    accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    # Names: nickname is the inviter's label; contact_full_name is the contact's
    # own account name (derived from the phone); display_name resolves between
    # them. is_app_user / contact_phone(_number) are derived model properties.
    nickname: str | None = None
    display_name: str | None = None
    contact_full_name: str | None = None
    is_app_user: bool = False
    contact_phone_number: str | None = None
    contact_phone: str | None = None
    phone_contact_id: str | None = None

    # SMS invitation fields
    sms_invitation_sent: bool = False
    sms_invitation_sent_at: datetime | None = None
    sms_message_id: str | None = None

    # Nudge tracking
    last_nudged_at: datetime | None = None
    can_nudge: bool = False

    @model_validator(mode="after")
    def compute_fields(self):
        if self.contact_phone is None:
            self.contact_phone = self.contact_phone_number
        if not self.can_nudge and self.status == ContactStatus.PENDING:
            if self.last_nudged_at is None:
                self.can_nudge = True
            else:
                self.can_nudge = datetime.now(UTC) - self.last_nudged_at >= timedelta(
                    hours=24
                )
        return self

    model_config = ConfigDict(from_attributes=True)


class CircleOfTrustSettingsCreate(BaseModel):
    """Schema for creating Circle of Trust settings"""

    max_contacts: int = 3
    auto_import_contacts: bool = False
    sms_invitations_enabled: bool = True
    notification_preferences: dict[str, Any] | None = None


class CircleOfTrustSettings(BaseModel):
    """Schema for Circle of Trust settings"""

    id: UUID
    user_id: UUID
    max_contacts: int = 3
    auto_import_contacts: bool = False
    sms_invitations_enabled: bool = True
    notification_preferences: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CircleOfTrustSettingsUpdate(BaseModel):
    """Schema for updating Circle of Trust settings"""

    max_contacts: int | None = None
    auto_import_contacts: bool | None = None
    sms_invitations_enabled: bool | None = None
    notification_preferences: dict[str, Any] | None = None
