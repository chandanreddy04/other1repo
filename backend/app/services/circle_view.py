"""Circle-viewer session snapshot — what an alerted contact may see.

Single source for the owner/session fields the public alert page
(web/routes_web.py `_alert_view_context`) exposes to a circle member — the
native app no longer shows circle members anything (owner decision
2026-09-22: members use mobile web only). Pure data: raw UTC datetimes and
E164 phone — the web layer formats local times on top of this.

Gating mirrors the public page: location only when the owner enabled
location sharing; battery has no toggle (permission-free, safety-critical)
and is always included when a reading exists.

Related: web/templates/alert_view.html.
"""

from datetime import datetime
from typing import TypedDict

from app.models.session import Session


class SessionSnapshot(TypedDict):
    user_name: str | None
    user_phone: str | None
    destination: str | None
    return_time: datetime | None
    tz_offset_minutes: int | None
    last_known_latitude: float | None
    last_known_longitude: float | None
    last_location_update: datetime | None
    last_battery_level: float | None
    last_battery_state: str | None
    outfit_photo_url: str | None
    location_sharing_enabled: bool
    session_status: str


def build_session_snapshot(session: Session) -> SessionSnapshot:
    """Snapshot of a session for a circle member's view. Requires
    session.user to be loaded (callers eager-load it)."""
    owner = session.user
    location_on = bool(session.location_sharing_enabled)
    # last_known_* / last_battery_* are column_propertys attached at runtime
    # in models/__init__.py, hence getattr (mypy can't see them on the class).
    return {
        "user_name": owner.full_name if owner else None,
        "user_phone": owner.phone_number if owner else None,
        "destination": session.destination,
        "return_time": session.expected_return_time,
        "tz_offset_minutes": session.tz_offset_minutes,
        "last_known_latitude": getattr(session, "last_known_latitude", None)
        if location_on
        else None,
        "last_known_longitude": getattr(session, "last_known_longitude", None)
        if location_on
        else None,
        "last_location_update": getattr(session, "last_location_update", None),
        # Battery has no sharing toggle — always shown when a reading exists.
        "last_battery_level": getattr(session, "last_battery_level", None),
        "last_battery_state": getattr(session, "last_battery_state", None),
        # The outfit photo exists specifically so searchers know what the
        # owner was wearing — attached deliberately at session creation.
        "outfit_photo_url": session.outfit_photo_url,
        "location_sharing_enabled": location_on,
        "session_status": str(session.status),
    }
