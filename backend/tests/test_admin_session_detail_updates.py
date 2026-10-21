"""Admin: everything captured during a session is shown inline on its detail
page — the location trail (map + table) and alerts — replacing the old
standalone "Location Updates" section.

This test is the KEEP-IN-SYNC guard referenced by sessions_view: if a section
stops rendering, it fails here. When a new kind of per-session captured data is
added, extend this test too.

Related: app/web/admin_registry.py (sessions_view + _session_capture_context),
app/web/admin_views.py (AdminRelatedConfig / detail hooks),
app/web/templates/admin/{detail,_session_capture}.html.
"""

import json
import re
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertStatus, AlertType
from app.models.session import Session, SessionStatus, SessionType
from app.models.session_update import SessionUpdate
from tests.helpers import create_test_user


async def _session(db: AsyncSession, phone: str) -> Session:
    owner = await create_test_user(db, phone_number=phone)
    session = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC),
        status=SessionStatus.ACTIVE.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
class TestAdminSessionDetailCapture:
    async def test_detail_shows_all_captured_data(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession
    ):
        session = await _session(db_session, "+14155599001")
        session.outfit_photo_url = "https://example.com/outfit.jpg"

        # Two location pings (a trail) and an alert.
        db_session.add_all(
            [
                SessionUpdate(
                    session_id=session.id,
                    latitude=37.7752,
                    longitude=-122.4194,
                    battery_level=0.42,
                    battery_state="unplugged",
                ),
                SessionUpdate(
                    session_id=session.id,
                    latitude=37.8000,
                    longitude=-122.4000,
                    battery_level=0.39,
                    battery_state="unplugged",
                ),
                Alert(
                    session_id=session.id,
                    sent_to_user_id=session.user_id,  # exactly one recipient set
                    alert_type=AlertType.MISSED_SESSION,
                    status=AlertStatus.SENT,
                    message="test",
                    sent_at=datetime.now(UTC),
                ),
            ]
        )
        await db_session.commit()

        r = await client.get(f"/admin/sessions/{session.id}", cookies=admin_cookies)
        assert r.status_code == 200
        body = r.text

        # Location trail: map div + trail header with the capture count.
        assert "session-map" in body
        assert "Location trail (2 captures)" in body
        # OSM raster tiles via Leaflet were replaced with MapLibre + the
        # OpenFreeMap "liberty" style (owner decision 2026-09-23: no map may
        # point at OpenStreetMap's own raw tile servers).
        assert "maplibre-gl@5.24.0" in body  # the map library is loaded
        assert "tile.openstreetmap.org" not in body
        # The trail is embedded as JSON for the map script, with the real
        # coordinates from both pings (chronological order).
        match = re.search(
            r'<script id="trail-data" type="application/json">(.*?)</script>',
            body,
            re.S,
        )
        assert match, "trail-data script tag not found"
        trail = json.loads(match.group(1))
        assert [(p["lat"], p["lng"]) for p in trail] == [
            (37.7752, -122.4194),
            (37.8, -122.4),
        ]
        # Exact-values table row (unlimited).
        assert "37.7752" in body
        assert "unplugged" in body
        # Alerts table.
        assert "Alerts fired (1)" in body
        # Outfit photo + the full captured session record (detail fields).
        assert "Outfit photo" in body
        assert "https://example.com/outfit.jpg" in body
        assert "Last Battery" in body
        assert "Data Purges After" in body
        # Order: alerts before the exact-values location table, which is last.
        assert body.index("Alerts fired") < body.index("Location &amp; battery updates")

    async def test_detail_ok_with_nothing_captured(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession
    ):
        session = await _session(db_session, "+14155599002")
        r = await client.get(f"/admin/sessions/{session.id}", cookies=admin_cookies)
        assert r.status_code == 200
        # No map when there are no points; empty related tables say so.
        assert "session-map" not in r.text
        assert "None recorded." in r.text

    async def test_standalone_location_updates_section_removed(
        self, client: AsyncClient, admin_cookies: dict
    ):
        for path in ("location-updates", "session-updates"):
            r = await client.get(f"/admin/{path}", cookies=admin_cookies)
            assert r.status_code == 404
