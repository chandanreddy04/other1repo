import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SubscriptionStatusResponse(BaseModel):
    has_access: bool
    # "subscription", "promotion", "referral_credit", "free_trial", "group_plan", "none"
    reason: str
    expires_at: datetime | None = None
    sessions_remaining: int | None = None
    plan_type: str | None = None
    group_plan_id: uuid.UUID | None = None
    group_plan_owner_name: str | None = None
    # SubscriptionSource of the backing row (stripe_web/stripe_gift/comp/...),
    # so the app can tell a self-paid plan (manageable in-app) from a
    # gift/comp/day-pass (status-only). None when access isn't a Subscription row.
    source: str | None = None
    # For a self-paid recurring subscription: True when scheduled to stop at
    # the period end (renders "Cancels …" + a Reactivate action), False when
    # renewing. None when the concept doesn't apply (group member, trial, etc.).
    cancel_at_period_end: bool | None = None


class SubscriptionUpdateRequest(BaseModel):
    # The only in-app-mutable field: True cancels at the paid period end
    # (service continues until then), False reactivates a pending cancel.
    cancel_at_period_end: bool


class GiftCheckoutRequest(BaseModel):
    recipient_phone: str = Field(
        ..., description="Recipient phone number in E164 format"
    )
    plan_type: str = Field(..., description="Plan type: monthly or annual")
    gifter_name: str = Field(..., description="Name of the person gifting")


class ReferralInfoResponse(BaseModel):
    referral_code: str
    can_refer: bool
    referrals_used: int
    referrals_max: int


class ApplyReferralRequest(BaseModel):
    referral_code: str = Field(..., min_length=8, max_length=8)


class CheckoutRequest(BaseModel):
    plan_type: str = Field(..., description="Plan type: monthly, annual, group_monthly, or group_annual")


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str
