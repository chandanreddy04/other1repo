from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.session import SessionStatus, SessionType
from app.services.photo_urls import to_viewable_url


class SessionCreate(BaseModel):
    session_type: SessionType = SessionType.CHECKIN
    expected_return_time: datetime | None = None
    # Client's UTC offset in minutes east of UTC (e.g. -420 for PDT), bounded
    # to real-world offsets (UTC-12..UTC+14). Lets alert copy render the
    # expected-return time in the owner's local time (stored times are UTC).
    # Optional for backward compatibility with older clients.
    tz_offset_minutes: int | None = Field(None, ge=-720, le=840)
    destination: str | None = Field(None, max_length=500)
    outfit_photo_url: str | None = None
    location_sharing_enabled: bool = False
    # Optional initial location snapshot. SOS uses it to attach the panicking
    # user's last-known position to the very first alert (which is dispatched
    # inline, before location tracking would produce an update).
    latitude: float | None = None
    longitude: float | None = None
    battery_level: float | None = Field(None, ge=0.0, le=1.0)
    battery_state: str | None = Field(
        None, pattern=r"^(charging|unplugged|full|unknown)$"
    )

    @model_validator(mode="after")
    def validate_by_type(self):
        if self.session_type == SessionType.CHECKIN:
            if self.expected_return_time is None:
                raise ValueError("expected_return_time is required for a check-in")
        elif self.session_type == SessionType.SOS:
            self.expected_return_time = datetime.now(UTC)
            self.destination = None
            self.outfit_photo_url = None
            # Emergency: share location + battery so the circle can find them
            # and know if the phone is about to die. The mobile attaches the
            # last-known location (below) so the first alert already has it.
            self.location_sharing_enabled = True
        return self


class SessionUpdate(BaseModel):
    destination: str | None = Field(None, max_length=500)
    location_sharing_enabled: bool | None = None


class SessionExtend(BaseModel):
    # Positive extends the deadline; negative brings it in — letting an owner
    # correct an accidental over-extend. 0 is a no-op and rejected. The endpoint
    # additionally rejects a reduction that would push the deadline into the
    # past (which would instantly trip the alert pipeline). Max ±4 hours.
    minutes_to_extend: int = Field(..., ge=-240, le=240)

    @model_validator(mode="after")
    def _reject_zero(self):
        if self.minutes_to_extend == 0:
            raise ValueError("minutes_to_extend must be non-zero")
        return self


class Session(BaseModel):
    id: UUID
    user_id: UUID
    session_type: SessionType
    expected_return_time: datetime
    actual_return_time: datetime | None
    destination: str | None
    outfit_photo_url: str | None
    outfit_photo_uploaded_at: datetime | None
    location_sharing_enabled: bool
    last_known_latitude: float | None
    last_known_longitude: float | None
    last_location_update: datetime | None
    last_battery_level: float | None
    last_battery_state: str | None
    status: SessionStatus
    # When post-session data (photos, location trail) is purged. Drives the
    # History screen's "data deleted {date}" + extend affordance.
    purge_after: datetime | None = None
    # When the data was ACTUALLY deleted (stamped by purge_session_data —
    # covers the admin early-purge path, which purge_after can't). Render the
    # deletion date from this; fall back to session end + retention days for
    # rows purged before the column existed.
    purged_at: datetime | None = None
    # When an admin cancelled the session (close-false-alarm). The neutral
    # session-end anchor for CANCELLED rows — never actual_return_time, which
    # would falsely claim the owner marked themselves safe.
    cancelled_at: datetime | None = None
    # True when ANY alert was ever dispatched for this session — drives the
    # summary screen's honest past tense ("Was shared with your Circle" vs
    # "Nothing was shared with your Circle"). Computed on the owner detail
    # endpoint; fail-safe False elsewhere (never claims sharing happened).
    was_alerted: bool = False
    # True when a circle member claimed an alert for this session ("I'm on
    # it"). Populated only by the owner poll endpoints (GET /sessions/{id}
    # and GET /sessions/active) — the reads the owner's active-session screen
    # and Live Activity render from; everywhere else it keeps the fail-safe
    # default (never claims acknowledgment untruthfully).
    alert_acknowledged: bool = False
    # True when the session is MISSED and every circle-alert delivery is
    # terminally undeliverable (or the circle emptied before dispatch) — the
    # owner must be told no one is coming instead of "notifying your circle…"
    # forever. Computed only on the owner poll endpoints; fail-safe False
    # everywhere else (never fabricates either comfort or alarm).
    circle_unreachable: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _sign_outfit_photo(self):
        # Raw private-S3 URL → viewable presigned URL. See photo_urls.py.
        self.outfit_photo_url = to_viewable_url(self.outfit_photo_url)
        return self


class RetentionAdjust(BaseModel):
    """Signed retention adjustment: +N extends the purge date, -N walks an
    extension back. Only ±RETENTION_EXTENSION_DAYS is accepted (endpoint-
    enforced); reductions are clamped to the floor — the higher of the
    ORIGINAL deletion date (session end + SESSION_DATA_RETENTION_DAYS) and
    now — so nobody can schedule deletion inside the original evidence
    window or in the past."""

    days: int


class SessionUpdateRequest(BaseModel):
    # Coordinates are optional so an opportunistic heartbeat can report battery
    # alone when location is off. They must be sent together (never one without
    # the other), and every update must carry SOMETHING (location, battery, or
    # both) — an empty payload is rejected.
    latitude: float | None = None
    longitude: float | None = None
    battery_level: float | None = Field(None, ge=0.0, le=1.0)
    battery_state: str | None = Field(None, pattern=r"^(charging|unplugged|full|unknown)$")

    @model_validator(mode="after")
    def _require_location_or_battery(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be provided together")
        has_coords = self.latitude is not None
        has_battery = self.battery_level is not None or self.battery_state is not None
        if not has_coords and not has_battery:
            raise ValueError("provide a location, a battery reading, or both")
        return self


class LocationPoint(BaseModel):
    latitude: float
    longitude: float
    battery_level: float | None
    battery_state: str | None
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)
