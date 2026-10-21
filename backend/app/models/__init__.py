from sqlalchemy import select
from sqlalchemy.orm import column_property

from app.models.account_grant import AccountGrant
from app.models.admin_access_log import AdminAccessLog
from app.models.alert import Alert
from app.models.circle_of_trust import CircleOfTrustMember
from app.models.circle_of_trust_settings import CircleOfTrustSettings
from app.models.group_plan import GroupPlan, GroupPlanMember
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.otp import OTP
from app.models.phone_number import PhoneNumber
from app.models.processed_stripe_event import ProcessedStripeEvent
from app.models.session import Session
from app.models.session_reminder import SessionReminder
from app.models.session_update import SessionUpdate
from app.models.sponsor import SponsorshipRequest
from app.models.sponsorship_sign_in_token import SponsorshipSignInToken
from app.models.subscription import Promotion, Referral, Subscription
from app.models.user import User

# Derive last-known location + battery from session_updates (avoids denormalized
# snapshot columns). Location and battery are sourced INDEPENDENTLY: a
# battery-only heartbeat (coords null) must not blank the last-known location, so
# location fields come from the latest COORD-bearing row and battery fields from
# the latest BATTERY-bearing row.
_latest_loc = (
    select(SessionUpdate)
    .where(
        SessionUpdate.session_id == Session.id,
        SessionUpdate.latitude.isnot(None),
    )
    .order_by(SessionUpdate.recorded_at.desc())
    .limit(1)
    .correlate(Session)
    .subquery()
)
_latest_battery = (
    select(SessionUpdate)
    .where(
        SessionUpdate.session_id == Session.id,
        SessionUpdate.battery_level.isnot(None),
    )
    .order_by(SessionUpdate.recorded_at.desc())
    .limit(1)
    .correlate(Session)
    .subquery()
)
Session.last_known_latitude = column_property(
    select(_latest_loc.c.latitude).scalar_subquery()
)
Session.last_known_longitude = column_property(
    select(_latest_loc.c.longitude).scalar_subquery()
)
Session.last_location_update = column_property(
    select(_latest_loc.c.recorded_at).scalar_subquery()
)
Session.last_battery_level = column_property(
    select(_latest_battery.c.battery_level).scalar_subquery()
)
Session.last_battery_state = column_property(
    select(_latest_battery.c.battery_state).scalar_subquery()
)

__all__ = [
    "OTP",
    "AccountGrant",
    "AdminAccessLog",
    "Alert",
    "CircleOfTrustMember",
    "CircleOfTrustSettings",
    "DeliveryChannel",
    "DeliveryStatus",
    "GroupPlan",
    "GroupPlanMember",
    "NotificationDelivery",
    "NotificationKind",
    "PhoneNumber",
    "ProcessedStripeEvent",
    "Promotion",
    "Referral",
    "Session",
    "SessionReminder",
    "SessionUpdate",
    "SponsorshipRequest",
    "SponsorshipSignInToken",
    "Subscription",
    "User",
]
