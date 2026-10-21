"""The public alert page's live sections (/alerts/{id}) — the layout added
to mirror the native alert-details screen (mobile/app/alert-details.tsx,
deleted; the web page is now the ONLY detail surface a Circle member sees,
owner decision 2026-09-23): From (full name), message, sent-at, the
Navigate + Call 911 actions, the location-trail map (sharing-gated, incl.
the one-fix case), device status with charging + last ping, the outfit
photo, no-referrer, and the section order.

Base parity (contact, location toggle, battery-no-toggle, destination,
expected time, last ping, Acknowledge) is covered by
test_alert_page_parity.py and test_no_app_contact_flows.py; this file
covers the sections that commit added on top.

Related: app/web/routes_web.py::_alert_view_context,
app/web/templates/alert_view.html, app/services/circle_view.py.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.services.session_tasks import _format_local_datetime
from app.utils.phone import format_for_display
from tests.helpers import create_test_user

_PHONE = iter(f"+141555940{n:02d}" for n in range(1, 99))

_MAPLIBRE_SCRIPT = (
    '<script src="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js"'
    ' integrity="sha384-5+cfbwT0iiub6VsQAdn6yz16nr6sDiQoHx6tm4O8OVYXHYOxcffFmCJBL0dgdvGp"'
    ' crossorigin="anonymous"></script>'
)


def _owner_e164(text: str) -> str:
    """The owner's E164 from the page's Call button (tel: href)."""
    match = re.search(r'href="tel:(\+\d+)"', text)
    assert match is not None
    return match.group(1)


async def _build(
    db: AsyncSession,
    *,
    alert_type: AlertType = AlertType.MISSED_SESSION,
    location_sharing: bool = True,
    with_trail: bool = False,
    battery_state: str | None = "charging",
    outfit_photo_url: str | None = "https://example.com/outfit.jpg",
    message: str = "This is the alert body text.",
    tz_offset_minutes: int = -420,  # PDT, well away from UTC
    single_fix: bool = False,
    status: str = SessionStatus.MISSED.value,
) -> Alert:
    owner = await create_test_user(db, phone_number=next(_PHONE), full_name="Ana Owner")
    contact = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Cody Contact"
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        destination="Central Park",
        status=status,
        tz_offset_minutes=tz_offset_minutes,
        location_sharing_enabled=location_sharing,
        outfit_photo_url=outfit_photo_url,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    if with_trail and not single_fix:
        # 2+ coord-bearing rows so the trail carries a real line, not a dot.
        db.add(
            SessionUpdate(
                session_id=session.id,
                latitude=40.7128,
                longitude=-74.0060,
                recorded_at=datetime.now(UTC) - timedelta(minutes=10),
            )
        )
        db.add(
            SessionUpdate(
                session_id=session.id,
                latitude=40.7580,
                longitude=-73.9855,
                battery_level=0.42,
                battery_state=battery_state,
                recorded_at=datetime.now(UTC) - timedelta(minutes=2),
            )
        )
    elif with_trail:
        # One fix only — e.g. a fresh SOS carrying just its last-known
        # snapshot: the map must render a marker, not a line/fitBounds.
        db.add(
            SessionUpdate(
                session_id=session.id,
                latitude=40.7580,
                longitude=-73.9855,
                battery_level=0.42,
                battery_state=battery_state,
                recorded_at=datetime.now(UTC) - timedelta(minutes=2),
            )
        )
    elif battery_state is not None:
        # Sharing-off case still wants a battery reading (no toggle) but no
        # coords at all.
        db.add(
            SessionUpdate(
                session_id=session.id,
                battery_level=0.42,
                battery_state=battery_state,
                recorded_at=datetime.now(UTC) - timedelta(minutes=2),
            )
        )
    await db.commit()
    await db.refresh(session)

    alert = Alert(
        session_id=session.id,
        sent_to_phone_id=contact.phone_number_id,
        alert_type=alert_type,
        status=AlertStatus.SENT,
        message=message,
        sent_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@pytest.mark.asyncio
class TestMessageAndSentAt:
    async def test_message_is_shown(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, with_trail=True)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "This is the alert body text." in resp.text

    async def test_sent_at_is_local_not_utc(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # No trail here — its timestamps are legitimately raw ISO8601/UTC
        # (machine-readable JSON for the map script); this test is only
        # about the human-facing "Sent at" fact.
        alert = await _build(db_session, with_trail=False, tz_offset_minutes=-420)
        resp = await client.get(f"/alerts/{alert.id}")
        local = _format_local_datetime(alert.sent_at, -420)
        assert local is not None
        assert local in resp.text
        # Never a raw UTC clock reading (owner decision — see
        # _format_local_time/_format_local_datetime docstrings).
        assert "UTC" not in resp.text
        assert alert.sent_at.isoformat() not in resp.text


@pytest.mark.asyncio
class TestCall911:
    async def test_call_911_present_on_both_alert_types(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        for alert_type in (AlertType.MISSED_SESSION, AlertType.PANIC):
            alert = await _build(db_session, alert_type=alert_type)
            resp = await client.get(f"/alerts/{alert.id}")
            assert 'href="tel:911"' in resp.text


@pytest.mark.asyncio
class TestBatteryCharging:
    async def test_charging_shown_when_charging(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, battery_state="charging")
        resp = await client.get(f"/alerts/{alert.id}")
        assert "Charging" in resp.text
        assert "42%" in resp.text

    async def test_charging_not_shown_for_other_states(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        for state in ("unplugged", "full", "unknown", None):
            alert = await _build(db_session, battery_state=state)
            resp = await client.get(f"/alerts/{alert.id}")
            assert "Charging" not in resp.text


@pytest.mark.asyncio
class TestOutfitPhoto:
    async def test_outfit_photo_shown_when_present(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(
            db_session, outfit_photo_url="https://example.com/outfit.jpg"
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert 'src="https://example.com/outfit.jpg"' in resp.text

    async def test_outfit_photo_absent_when_not_set(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, outfit_photo_url=None)
        resp = await client.get(f"/alerts/{alert.id}")
        assert "Outfit photo" not in resp.text
        assert "<img" not in resp.text


@pytest.mark.asyncio
class TestLocationTrailMap:
    async def test_map_and_trail_json_shown_when_sharing_on(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, location_sharing=True, with_trail=True)
        resp = await client.get(f"/alerts/{alert.id}")
        assert 'id="map"' in resp.text
        # The exact points, serialised by the template's |tojson.
        assert '"lat": 40.7128' in resp.text
        assert '"lng": -74.006' in resp.text
        assert '"lat": 40.758' in resp.text
        assert '"lng": -73.9855' in resp.text
        assert resp.text.count(_MAPLIBRE_SCRIPT) == 1
        # The Google Maps hand-off is a Take-action button, visible with or
        # without JS — the no-JS / blocked-CDN fallback for the map.
        assert "maps.google.com" in resp.text

    @pytest.mark.parametrize("alert_type", [AlertType.MISSED_SESSION, AlertType.PANIC])
    async def test_no_map_or_coords_when_sharing_off(
        self, client: AsyncClient, db_session: AsyncSession, alert_type: AlertType
    ):
        # Coordinate rows EXIST — the page must still show none of them
        # (gated on the session's toggle, whatever the alert type).
        alert = await _build(
            db_session,
            alert_type=alert_type,
            location_sharing=False,
            with_trail=True,
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert 'id="map"' not in resp.text
        assert "trail-data" not in resp.text
        assert "maplibre-gl" not in resp.text
        assert "maps.google.com" not in resp.text
        assert "Navigate to last known location" not in resp.text
        for coord in ("40.7128", "-74.006", "40.758", "-73.9855"):
            assert coord not in resp.text
        # Battery and last ping have no toggle — still shown.
        assert "42%" in resp.text
        assert "Last pinged" in resp.text

    async def test_single_fix_renders_the_map(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, with_trail=True, single_fix=True)
        resp = await client.get(f"/alerts/{alert.id}")
        assert 'id="map"' in resp.text
        assert '[{"lat": 40.758, "lng": -73.9855}]' in resp.text
        assert resp.text.count(_MAPLIBRE_SCRIPT) == 1
        # The script's one-fix branch: no line and no zero-area fitBounds.
        assert "coords.length < 2" in resp.text
        assert "maxZoom: 16" in resp.text

    async def test_map_script_hides_only_on_genuine_failure(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Browser gut-check: the old script hid the section on ANY pre-load
        # `error` event (a sprite/tile failure) or when `load` hadn't fired
        # within 10 s (slow tiles), though the map was rendering. The
        # structure below is what keeps a working map on the page; the
        # behaviour itself is re-checked in a real browser.
        alert = await _build(db_session, with_trail=True)
        text = (await client.get(f"/alerts/{alert.id}")).text
        start = text.index("var STYLE_URL")
        script = text[start : text.index("</script>", start)]
        # Once the style has arrived nothing hides the section again.
        assert "if (working) { return; }" in script
        assert "map.on('styledata', markWorking)" in script
        assert "map.on('load', markWorking)" in script
        # Only the style request's own failure is fatal on `error`.
        assert "!working && isStyleFailure(e)" in script
        assert "url.split('?')[0] === STYLE_URL" in script
        # The style URL the check compares against is the one loaded.
        assert "style: STYLE_URL" in script
        assert "'https://tiles.openfreemap.org/styles/liberty'" in script
        # Generous no-style timeout, cleared once working.
        assert "var STYLE_TIMEOUT = 20000;" in script
        assert "setTimeout(hide, STYLE_TIMEOUT)" in script
        # Missing POI icons get a transparent placeholder, not a warning.
        assert "map.on('styleimagemissing'" in script
        assert "map.addImage(e.id, { width: 1, height: 1" in script
        # Blocked CDN and no-JS fallbacks are kept.
        assert "if (typeof maplibregl === 'undefined') { hide(); return; }" in script
        assert (
            "<noscript><style>#location-history { display: none; }</style></noscript>"
            in text
        )
        # The old "any pre-load error hides" handler is gone.
        assert "isStyleLoaded" not in script
        assert "if (!loaded)" not in script

    async def test_trail_json_is_html_safe_and_coords_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, with_trail=True)
        resp = await client.get(f"/alerts/{alert.id}")
        start = resp.text.index('<script id="trail-data" type="application/json">')
        blob = resp.text[start : resp.text.index("</script>", start)]
        # |tojson — coordinates only (no raw UTC timestamps on the page).
        assert '"at"' not in blob
        assert '"lat": 40.7128' in blob

    async def test_navigate_button_in_take_action_when_sharing_on(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, with_trail=True)
        text = (await client.get(f"/alerts/{alert.id}")).text
        assert "Navigate to last known location" in text
        assert "https://maps.google.com/?q=40.758,-73.9855" in text
        assert text.index("Navigate to last known location") < text.index(
            'href="tel:911"'
        )

    async def test_no_map_assets_on_the_all_clear_card(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(
            db_session, with_trail=True, status=SessionStatus.COMPLETED.value
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert "All clear" in resp.text
        assert "maplibre-gl" not in resp.text
        assert "trail-data" not in resp.text


@pytest.mark.asyncio
class TestFromAndReferrer:
    async def test_from_shows_full_name_and_phone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session)
        text = (await client.get(f"/alerts/{alert.id}")).text
        phone = format_for_display(_owner_e164(text))
        assert phone.startswith("(")  # the display form carries its own parens
        assert f"Ana Owner · {phone}" in text

    async def test_call_button_shows_phone_once_without_double_parens(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # format_for_display already renders "(415) 555-0137"; wrapping it in
        # another pair gave "Call Ana ((415) 555-0137)" (browser gut-check).
        alert = await _build(db_session)
        text = (await client.get(f"/alerts/{alert.id}")).text
        e164 = _owner_e164(text)
        phone = format_for_display(e164)
        assert f'href="tel:{e164}">Call Ana · {phone}</a>' in text
        assert "((" not in text
        assert "))" not in text

    async def test_page_sends_no_referrer(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # The URL is the access token; third-party requests must not carry it.
        alert = await _build(db_session, with_trail=True)
        text = (await client.get(f"/alerts/{alert.id}")).text
        assert '<meta name="referrer" content="no-referrer">' in text


@pytest.mark.asyncio
class TestSosAndMissedSectionParity:
    async def test_new_sections_match_except_header_and_banner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        common = {
            "with_trail": True,
            "battery_state": "charging",
            "outfit_photo_url": "https://example.com/outfit.jpg",
            "message": "Shared alert body.",
        }
        missed = await _build(db_session, alert_type=AlertType.MISSED_SESSION, **common)
        sos = await _build(db_session, alert_type=AlertType.PANIC, **common)

        missed_text = (await client.get(f"/alerts/{missed.id}")).text
        sos_text = (await client.get(f"/alerts/{sos.id}")).text

        for token in (
            "Shared alert body.",  # message
            'href="tel:911"',  # Call 911
            'id="map"',  # trail map
            "Navigate to last known location",  # map hand-off / fallback
            "Charging",  # device status
            "42%",
            "Last pinged",  # device status
            "Ana Owner · (",  # From: full name + phone
            'src="https://example.com/outfit.jpg"',  # outfit photo
            "Central Park",  # session details
            "Acknowledge",
        ):
            assert token in missed_text, f"missed page missing {token}"
            assert token in sos_text, f"sos page missing {token}"

        # The only intended difference: the trigger header/banner.
        assert "Missed check-in alert" in missed_text
        assert "SOS alert" in sos_text
        assert "SOS alert" not in missed_text
        assert "Missed check-in alert" not in sos_text
        assert "missed their check-in" in missed_text
        assert "pressed SOS" in sos_text
        assert "pressed SOS" not in missed_text
        assert "missed their check-in" not in sos_text


@pytest.mark.asyncio
class TestSectionOrder:
    async def test_sections_follow_the_native_alert_details_order(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        alert = await _build(db_session, with_trail=True)
        text = (await client.get(f"/alerts/{alert.id}")).text
        order = [
            "Missed check-in alert",  # 1. header
            ">From<",  # 2. from / sent at / message
            ">Sent at<",
            "Message",
            ">Take action<",  # 3.
            ">Location history<",  # 4.
            ">Session details<",  # 5.
            ">Device status<",  # 6.
            ">Last pinged<",
            ">Outfit photo<",  # 7.
            "What to do:",  # 8.
        ]
        positions = [text.index(marker) for marker in order]
        assert positions == sorted(positions)
