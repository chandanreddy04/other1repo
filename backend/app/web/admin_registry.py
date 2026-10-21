"""Registry of all admin model views. Each entity is configured here.

row_class callbacks (_alert_row_class, _session_row_class) add CSS
classes for conditional row highlighting in the admin table.

Related: web/admin_views.py, web/templates/admin/
"""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from app.core.config import settings
from app.crud.phone_number import crud_phone_number
from app.models.account_grant import AccountGrant
from app.models.admin_access_log import AdminAccessLog
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.group_plan import GroupPlan, GroupPlanMember
from app.models.otp import OTP
from app.models.phone_number import PhoneNumber
from app.models.session import Session, SessionStatus, SessionType
from app.models.session_update import SessionUpdate
from app.models.sponsor import SponsorshipRequest, SponsorshipRequestStatus
from app.models.subscription import (
    PlanType,
    Promotion,
    Referral,
    ReferralStatus,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User
from app.services.photo_urls import to_viewable_url
from app.utils.phone import format_to_e164
from app.web.admin_views import (
    AdminColumnConfig,
    AdminFilterConfig,
    AdminModelView,
    AdminRelatedConfig,
)


def _enum_choices(enum_cls) -> list[tuple[str, str]]:
    """Convert an enum to (value, display) pairs for filter/form dropdowns."""
    return [(e.value, e.value.replace("_", " ").title()) for e in enum_cls]


def _phone_formatter(phone) -> str:
    """Format a PhoneNumber relationship object."""
    if hasattr(phone, "number"):
        return phone.number
    return str(phone) if phone else "—"


def _alert_row_class(alert) -> str:
    # Delivery retries now live in notification_deliveries; a FAILED alert
    # (its deliveries exhausted) is the flag worth surfacing here.
    if alert.status == AlertStatus.FAILED:
        return "row-warning"
    return ""


def _session_row_class(session) -> str:
    from datetime import UTC, datetime, timedelta

    if (
        session.status == SessionStatus.MISSED
        and session.updated_at
        and session.updated_at < datetime.now(UTC) - timedelta(minutes=10)
    ):
        return "row-warning"
    return ""


# ── Core entities ──

users_view = AdminModelView(
    model=User,
    name="user",
    name_plural="users",
    section="users",
    eager_loads=[User.phone],
    columns=[
        AdminColumnConfig("full_name", "Name", searchable=True, link_to_detail=True),
        AdminColumnConfig(
            "phone",
            "Phone",
            searchable=True,
            formatter=_phone_formatter,
            join_model=PhoneNumber,
            join_attr="number",
        ),
        AdminColumnConfig("is_active", "Active"),
        AdminColumnConfig("is_admin", "Admin"),
        AdminColumnConfig("share_code", "Referral Code"),
        AdminColumnConfig("created_at", "Created"),
    ],
    detail_fields=[
        AdminColumnConfig("full_name", "Name"),
        AdminColumnConfig("phone", "Phone", formatter=_phone_formatter),
        AdminColumnConfig("is_active", "Active"),
        AdminColumnConfig("is_admin", "Admin"),
        AdminColumnConfig("phone_ownership_verified", "Phone Verified"),
        AdminColumnConfig("share_code", "Referral Code"),
        AdminColumnConfig("circle_invite_code", "Circle Invite Code"),
        AdminColumnConfig("max_referral_redemptions", "Max Referrals"),
        AdminColumnConfig("free_credit_end", "Free Credit End"),
        AdminColumnConfig("profile_photo_url", "Profile Photo URL"),
        AdminColumnConfig("expo_push_token", "Push Token"),
        AdminColumnConfig("created_at", "Created"),
        AdminColumnConfig("updated_at", "Updated"),
    ],
    filters=[
        AdminFilterConfig("is_active", "Status", [("True", "Active"), ("False", "Inactive")]),
        AdminFilterConfig("is_admin", "Role", [("True", "Admin"), ("False", "Regular")]),
    ],
    form_fields=[
        ("full_name", "Full Name", "text", None),
        ("is_active", "Active", "bool", None),
        ("is_admin", "Admin", "bool", None),
        ("max_referral_redemptions", "Max Referral Redemptions", "number", None),
        ("free_credit_end", "Free Credit End", "datetime", None),
    ],
)

# --- Session detail: everything captured during a session ------------------
# KEEP IN SYNC: sessions_view surfaces ALL per-session captured data on the
# detail page — location pings (session_updates → map + table), alerts
# (alerts → table). If a NEW kind of
# per-session captured data is added, add it here (a `related` table and/or
# the capture context below) so the admin keeps showing the full picture.
# Enforced by tests/test_admin_session_detail_updates.py.


def _fmt_dt(dt: Any) -> str:
    return dt.strftime("%b %d, %Y %H:%M:%S") if dt else "—"


def _fmt_battery(level: Any, state: Any) -> str | None:
    if level is None:
        return None
    pct = f"{round(level * 100)}%"
    return f"{pct} ({state})" if state else pct


async def _session_capture_context(db: Any, session: Any) -> dict:
    """Location trail (chronological) + alerts for the session detail page.
    Rendered by admin/_session_capture.html."""
    updates = (
        (
            await db.execute(
                select(SessionUpdate)
                .where(SessionUpdate.session_id == session.id)
                .order_by(SessionUpdate.recorded_at.asc())
            )
        )
        .scalars()
        .all()
    )
    # Map trail = coord-bearing rows only; battery-only heartbeats have no point
    # to plot (they still appear in the SessionUpdate related table below).
    # ts_ms lets the template's JS decide live whether the latest fix is stale
    # (pulsing blue dot vs static gray — same treatment as the mobile app).
    location_points = [
        {
            "lat": u.latitude,
            "lng": u.longitude,
            "ts": _fmt_dt(u.recorded_at),
            "ts_ms": int(u.recorded_at.timestamp() * 1000),
            "battery": _fmt_battery(u.battery_level, u.battery_state),
        }
        for u in updates
        if u.latitude is not None and u.longitude is not None
    ]

    alerts = (
        (
            await db.execute(
                select(Alert)
                .where(Alert.session_id == session.id)
                .order_by(Alert.sent_at.desc())
            )
        )
        .scalars()
        .all()
    )
    alert_rows = [
        {
            "type": a.alert_type.value,
            "status": a.status.value,
            "sent_at": _fmt_dt(a.sent_at),
            "delivered_at": _fmt_dt(a.delivered_at),
            "acknowledged_at": _fmt_dt(a.acknowledged_at),
        }
        for a in alerts
    ]

    # Every ping (battery-only rows included) with per-row clear controls —
    # rendered as the "Manage captured entries" table in _session_capture.html.
    update_rows = [
        {
            "id": str(u.id),
            "ts": _fmt_dt(u.recorded_at),
            "coords": (
                f"{u.latitude:.5f}, {u.longitude:.5f}"
                if u.latitude is not None and u.longitude is not None
                else None
            ),
            "battery": _fmt_battery(u.battery_level, u.battery_state),
        }
        for u in updates
    ]

    return {
        "location_points": location_points,
        "alert_rows": alert_rows,
        "update_rows": update_rows,
        "outfit_photo_url": to_viewable_url(session.outfit_photo_url),
        # Live session = the latest fix is a position claim; terminal sessions
        # render a plain end marker (no liveness to claim either way).
        "session_is_live": session.status
        in (SessionStatus.ACTIVE, SessionStatus.MISSED, SessionStatus.ALERTED),
        "location_stale_threshold_ms": settings.LOCATION_STALE_THRESHOLD_MINUTES
        * 60
        * 1000,
    }


sessions_view = AdminModelView(
    model=Session,
    name="session",
    name_plural="sessions",
    section="sessions",
    eager_loads=[Session.user],
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("user.full_name", "User", searchable=False),
        AdminColumnConfig("session_type", "Type"),
        AdminColumnConfig("status", "Status"),
        AdminColumnConfig("destination", "Destination", searchable=True),
        AdminColumnConfig("expected_return_time", "Expected Return"),
        AdminColumnConfig("updated_at", "Updated"),
        AdminColumnConfig("created_at", "Created"),
    ],
    # Full captured session record on the detail page (the list shows a subset).
    detail_fields=[
        AdminColumnConfig("user.full_name", "User"),
        AdminColumnConfig("session_type", "Type"),
        AdminColumnConfig("status", "Status"),
        AdminColumnConfig("destination", "Destination"),
        AdminColumnConfig("expected_return_time", "Expected Return"),
        AdminColumnConfig("actual_return_time", "Actual Return"),
        AdminColumnConfig("location_sharing_enabled", "Location Sharing"),
        AdminColumnConfig("last_known_latitude", "Last Latitude"),
        AdminColumnConfig("last_known_longitude", "Last Longitude"),
        AdminColumnConfig("last_location_update", "Last Location Update"),
        AdminColumnConfig("last_battery_level", "Last Battery"),
        AdminColumnConfig("last_battery_state", "Last Battery State"),
        AdminColumnConfig("outfit_photo_uploaded_at", "Outfit Photo Uploaded"),
        AdminColumnConfig("tz_offset_minutes", "TZ Offset (min)"),
        AdminColumnConfig("purge_after", "Data Purges After"),
        AdminColumnConfig("purged_at", "Data Purged At"),
        AdminColumnConfig("cancelled_at", "Cancelled At"),
        AdminColumnConfig("created_at", "Created"),
        AdminColumnConfig("updated_at", "Updated"),
    ],
    filters=[
        AdminFilterConfig("session_type", "Type", _enum_choices(SessionType)),
        AdminFilterConfig("status", "Status", _enum_choices(SessionStatus)),
    ],
    form_fields=[
        ("session_type", "Type", "select", _enum_choices(SessionType)),
        ("status", "Status", "select", _enum_choices(SessionStatus)),
        ("destination", "Destination", "text", None),
        ("expected_return_time", "Expected Return Time", "datetime", None),
        ("user_id", "User ID", "text", None),
    ],
    row_class=_session_row_class,
    # Everything captured during a session lives on its detail page (no
    # separate top-level sections). See the KEEP IN SYNC note above.
    detail_extra_template="admin/_session_capture.html",  # outfit + location map + alerts
    detail_context_hook=_session_capture_context,
    # Rendered LAST (related tables come after the detail_extra_template's
    # outfit / map / alerts). The exact-values location table sits at the
    # very end.
    related=[
        AdminRelatedConfig(
            title="Location & battery updates",
            model=SessionUpdate,
            foreign_key="session_id",
            order_by="recorded_at",  # chronological, matches the trail
            limit=None,  # show everything
            columns=[
                AdminColumnConfig("recorded_at", "Recorded At"),
                AdminColumnConfig("latitude", "Latitude"),
                AdminColumnConfig("longitude", "Longitude"),
                AdminColumnConfig("battery_level", "Battery"),
                AdminColumnConfig("battery_state", "State"),
            ],
        ),
    ],
)

alerts_view = AdminModelView(
    model=Alert,
    name="alert",
    name_plural="alerts",
    section="alerts",
    eager_loads=[Alert.session, Alert.sent_to_user],
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("sent_to_user.full_name", "Sent To"),
        AdminColumnConfig("alert_type", "Type"),
        AdminColumnConfig("status", "Status"),
        AdminColumnConfig("sent_at", "Sent At"),
        AdminColumnConfig("delivered_at", "Delivered At"),
        AdminColumnConfig("failed_at", "Failed At"),
    ],
    detail_fields=[
        AdminColumnConfig("id", "ID"),
        AdminColumnConfig("sent_to_user.full_name", "Sent To"),
        AdminColumnConfig("alert_type", "Type"),
        AdminColumnConfig("status", "Status"),
        AdminColumnConfig("message", "Message"),
        AdminColumnConfig("sent_at", "Sent At"),
        AdminColumnConfig("delivered_at", "Delivered At"),
        AdminColumnConfig("acknowledged_at", "Acknowledged At"),
        AdminColumnConfig("failed_at", "Failed At"),
        AdminColumnConfig("resolved_at", "Resolved At"),
        AdminColumnConfig("session_id", "Session ID"),
        AdminColumnConfig("created_at", "Created"),
    ],
    filters=[
        AdminFilterConfig("alert_type", "Type", _enum_choices(AlertType)),
        AdminFilterConfig("status", "Status", _enum_choices(AlertStatus)),
    ],
    form_fields=[
        ("alert_type", "Type", "select", _enum_choices(AlertType)),
        ("status", "Status", "select", _enum_choices(AlertStatus)),
        ("message", "Message", "textarea", None),
        ("session_id", "Session ID", "text", None),
        ("sent_to_user_id", "Sent To User ID", "text", None),
    ],
    row_class=_alert_row_class,
)

# ── Social ──

circle_members_view = AdminModelView(
    model=CircleOfTrustMember,
    name="circle member",
    name_plural="circle-members",
    section="circle-members",
    eager_loads=[CircleOfTrustMember.user, CircleOfTrustMember.contact_user],
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("user.full_name", "Owner"),
        AdminColumnConfig("nickname", "Nickname", searchable=True),
        AdminColumnConfig("contact_user.full_name", "Member account"),
        AdminColumnConfig("status", "Status"),
        AdminColumnConfig("created_at", "Created"),
    ],
    filters=[
        AdminFilterConfig("status", "Status", _enum_choices(ContactStatus)),
    ],
    form_fields=[
        ("nickname", "Nickname", "text", None),
        ("status", "Status", "select", _enum_choices(ContactStatus)),
        ("user_id", "Owner User ID", "text", None),
    ],
)

# ── Payments ──

subscriptions_view = AdminModelView(
    model=Subscription,
    name="subscription",
    name_plural="subscriptions",
    section="subscriptions",
    eager_loads=[Subscription.user, Subscription.phone],
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("user.full_name", "User"),
        AdminColumnConfig("phone", "Phone", formatter=_phone_formatter),
        AdminColumnConfig("plan_type", "Plan"),
        AdminColumnConfig("status", "Status"),
        AdminColumnConfig("source", "Source"),
        AdminColumnConfig("current_period_end", "Expires"),
    ],
    filters=[
        AdminFilterConfig("plan_type", "Plan", _enum_choices(PlanType)),
        AdminFilterConfig("status", "Status", _enum_choices(SubscriptionStatus)),
        AdminFilterConfig("source", "Source", _enum_choices(SubscriptionSource)),
    ],
    form_fields=[
        ("plan_type", "Plan Type", "select", _enum_choices(PlanType)),
        ("status", "Status", "select", _enum_choices(SubscriptionStatus)),
        ("source", "Source", "select", _enum_choices(SubscriptionSource)),
        ("current_period_start", "Period Start", "datetime", None),
        ("current_period_end", "Period End", "datetime", None),
        ("auto_renew", "Auto Renew", "bool", None),
        ("user_id", "User ID", "text", None),
        ("phone_number_id", "Phone Number ID", "text", None),
    ],
)

referrals_view = AdminModelView(
    model=Referral,
    name="referral",
    name_plural="referrals",
    section="referrals",
    eager_loads=[Referral.referrer, Referral.referee],
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("referral_code", "Code", searchable=True),
        AdminColumnConfig("referrer.full_name", "Referrer"),
        AdminColumnConfig("referee.full_name", "Referee"),
        AdminColumnConfig("status", "Status"),
        AdminColumnConfig("created_at", "Created"),
    ],
    filters=[
        AdminFilterConfig("status", "Status", _enum_choices(ReferralStatus)),
    ],
    form_fields=[
        ("referral_code", "Referral Code", "text", None),
        ("status", "Status", "select", _enum_choices(ReferralStatus)),
        ("referrer_user_id", "Referrer User ID", "text", None),
        ("referee_user_id", "Referee User ID", "text", None),
    ],
)

promotions_view = AdminModelView(
    model=Promotion,
    name="promotion",
    name_plural="promotions",
    section="promotions",
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("name", "Name", searchable=True),
        AdminColumnConfig("start_date", "Start"),
        AdminColumnConfig("end_date", "End"),
        AdminColumnConfig("is_active", "Active"),
        AdminColumnConfig("created_at", "Created"),
    ],
    filters=[
        AdminFilterConfig("is_active", "Active", [("True", "Active"), ("False", "Inactive")]),
    ],
    form_fields=[
        ("name", "Name", "text", None),
        ("start_date", "Start Date", "datetime", None),
        ("end_date", "End Date", "datetime", None),
        ("is_active", "Active", "bool", None),
    ],
)

group_plans_view = AdminModelView(
    model=GroupPlan,
    name="group plan",
    name_plural="group-plans",
    section="group-plans",
    eager_loads=[GroupPlan.owner],
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("owner.full_name", "Owner"),
        AdminColumnConfig("invite_code", "Invite Code", searchable=True),
        AdminColumnConfig("max_members", "Max Members"),
        AdminColumnConfig("created_at", "Created"),
    ],
    form_fields=[
        ("invite_code", "Invite Code", "text", None),
        ("max_members", "Max Members", "number", None),
        ("owner_user_id", "Owner User ID", "text", None),
        ("subscription_id", "Subscription ID", "text", None),
    ],
    # Members live on the group plan's detail page, not a standalone section.
    related=[
        AdminRelatedConfig(
            title="Group members",
            model=GroupPlanMember,
            foreign_key="group_plan_id",
            order_by="joined_at",
            limit=None,
            columns=[
                AdminColumnConfig("user.full_name", "User"),
                AdminColumnConfig("role", "Role"),
                AdminColumnConfig("joined_at", "Joined"),
                AdminColumnConfig("left_at", "Left"),
            ],
        ),
    ],
)

# (Group members are shown on the group plan's detail page — see
# group_plans_view.related — not a standalone admin section.)

sponsorship_requests_view = AdminModelView(
    model=SponsorshipRequest,
    name="sponsorship request",
    name_plural="sponsorship-requests",
    section="sponsorship-requests",
    read_only=True,
    eager_loads=[SponsorshipRequest.requester_phone, SponsorshipRequest.target_phone],
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig(
            "requester_phone", "Requester", formatter=_phone_formatter
        ),
        AdminColumnConfig("target_phone", "Target", formatter=_phone_formatter),
        AdminColumnConfig("status", "Status"),
        AdminColumnConfig("requested_at", "Requested"),
        AdminColumnConfig("fulfilled_at", "Fulfilled"),
    ],
    filters=[
        AdminFilterConfig("status", "Status", _enum_choices(SponsorshipRequestStatus)),
    ],
)

# ── System (view-only) ──

otps_view = AdminModelView(
    model=OTP,
    name="otp",
    name_plural="otps",
    section="otps",
    read_only=True,
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("phone_number", "Phone", searchable=True),
        AdminColumnConfig("is_used", "Used"),
        AdminColumnConfig("is_verified", "Verified"),
        AdminColumnConfig("created_at", "Created"),
        AdminColumnConfig("expires_at", "Expires"),
    ],
)

phone_numbers_view = AdminModelView(
    model=PhoneNumber,
    name="phone number",
    name_plural="phone-numbers",
    section="phone-numbers",
    read_only=True,
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("number", "Number", searchable=True),
        AdminColumnConfig("verified", "Verified"),
        AdminColumnConfig("created_at", "Created"),
    ],
)

admin_access_logs_view = AdminModelView(
    model=AdminAccessLog,
    name="admin access log",
    name_plural="admin-access-logs",
    section="admin-access-logs",
    read_only=True,
    eager_loads=[AdminAccessLog.admin_user, AdminAccessLog.target_user],
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig("admin_user.full_name", "Admin"),
        AdminColumnConfig("entity", "Entity", searchable=True),
        AdminColumnConfig("action", "Action"),
        AdminColumnConfig("entity_id", "Entity ID"),
        AdminColumnConfig("target_user.full_name", "Target User"),
        AdminColumnConfig("created_at", "When"),
    ],
    filters=[
        AdminFilterConfig(
            "action",
            "Action",
            [
                ("list", "List"),
                ("view_detail", "View Detail"),
                ("edit", "Edit"),
                ("create", "Create"),
                ("delete", "Delete"),
            ],
        ),
        AdminFilterConfig("entity", "Entity", [
            ("user", "User"),
            ("session", "Session"),
            ("alert", "Alert"),
            ("circle member", "Circle Member"),
            ("subscription", "Subscription"),
        ]),
    ],
)

async def _resolve_account_grant_phone(db, obj_data):
    """Map the admin form's ``phone_number`` string to a ``phone_number_id`` FK,
    creating the PhoneNumber if needed. Keeps AccountGrant convention-compliant
    (no phone string column) while letting admins type a plain number."""
    number = obj_data.pop("phone_number", None)
    if number:
        e164 = format_to_e164(number) or number
        phone, _ = await crud_phone_number.get_or_create(db, number=e164)
        obj_data["phone_number_id"] = phone.id
    return obj_data


account_grants_view = AdminModelView(
    model=AccountGrant,
    name="account grant",
    name_plural="account-grants",
    section="account-grants",
    columns=[
        AdminColumnConfig("id", "ID", link_to_detail=True),
        AdminColumnConfig(
            "phone.number",
            "Phone",
            sortable=False,
            searchable=True,
            join_model=PhoneNumber,
            join_attr="number",
        ),
        AdminColumnConfig("label", "Label", searchable=True),
        AdminColumnConfig("otp_code", "Login code"),
        AdminColumnConfig("enabled", "Enabled"),
        AdminColumnConfig("created_at", "Created"),
    ],
    filters=[
        AdminFilterConfig(
            "enabled", "Enabled", [("True", "Enabled"), ("False", "Disabled")]
        ),
    ],
    form_fields=[
        ("phone_number", "Phone (E164)", "text", None),
        ("label", "Label (why granted)", "text", None),
        ("otp_code", "Fixed login code — blank = normal SMS OTP", "text", None),
        ("enabled", "Enabled", "bool", None),
    ],
    form_transform=_resolve_account_grant_phone,
)


ALL_VIEWS = [
    users_view,
    sessions_view,
    alerts_view,
    circle_members_view,
    subscriptions_view,
    referrals_view,
    promotions_view,
    account_grants_view,
    group_plans_view,
    sponsorship_requests_view,
    otps_view,
    phone_numbers_view,
    admin_access_logs_view,
]


def register_all(router: APIRouter) -> None:
    """Register all admin model views on the given router."""
    for view in ALL_VIEWS:
        view.register_routes(router)
