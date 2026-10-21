"""Battery-only session updates (opportunistic heartbeat).

A session_update may carry battery alone when location is off. These guard that:
 - a battery-only update is accepted (and allowed even when location sharing is
   off, since battery has no toggle),
 - it never blanks the last-known location (location + battery derive from
   independent latest-rows),
 - the location trail excludes battery-only rows,
 - malformed payloads (partial coords, empty) are rejected.

Related: app/schemas/session.py (SessionUpdateRequest validator),
         app/models/__init__.py (column_property split),
         app/api/v1/endpoints/sessions.py (update_location).
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.session import Session, SessionStatus
from app.models.user import User
from tests.helpers import create_test_user


async def _create_user(db: AsyncSession, phone_number: str) -> User:
    return await create_test_user(db, phone_number=phone_number, full_name="Test User")


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _create_session(
    db: AsyncSession, user: User, *, location_sharing: bool = True
) -> Session:
    session = Session(
        user_id=user.id,
        expected_return_time=datetime.now(UTC) + timedelta(hours=2),
        destination="Test Destination",
        location_sharing_enabled=location_sharing,
        status=SessionStatus.ACTIVE.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
class TestBatteryOnlyUpdates:
    async def test_battery_only_update_succeeds(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155580100")
        session = await _create_session(db_session, user)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"battery_level": 0.42, "battery_state": "unplugged"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["last_battery_level"] == 0.42
        assert data["last_battery_state"] == "unplugged"
        # No coordinates were sent, so there is no last-known location.
        assert data["last_known_latitude"] is None
        assert data["last_known_longitude"] is None

    async def test_battery_only_allowed_when_location_sharing_off(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155580101")
        session = await _create_session(db_session, user, location_sharing=False)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"battery_level": 0.30, "battery_state": "charging"},
        )
        assert response.status_code == 200
        assert response.json()["last_battery_level"] == 0.30

    async def test_location_update_still_blocked_when_sharing_off(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155580102")
        session = await _create_session(db_session, user, location_sharing=False)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 40.7, "longitude": -74.0, "battery_level": 0.9},
        )
        assert response.status_code == 400

    async def test_battery_only_ping_preserves_last_known_location(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155580103")
        session = await _create_session(db_session, user)

        # First a real location ping...
        await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 37.7749, "longitude": -122.4194, "battery_level": 0.8},
        )
        # ...then a later battery-only heartbeat.
        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"battery_level": 0.55, "battery_state": "unplugged"},
        )
        assert response.status_code == 200
        data = response.json()
        # Location is retained from the earlier coord-bearing row...
        assert data["last_known_latitude"] == 37.7749
        assert data["last_known_longitude"] == -122.4194
        # ...while battery reflects the freshest reading.
        assert data["last_battery_level"] == 0.55
        assert data["last_battery_state"] == "unplugged"

    async def test_location_history_excludes_battery_only_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155580104")
        session = await _create_session(db_session, user)

        await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 37.77, "longitude": -122.41},
        )
        await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"battery_level": 0.5},
        )

        response = await client.get(
            f"/api/v1/sessions/{session.id}/locations", headers=_auth(user)
        )
        assert response.status_code == 200
        history = response.json()
        assert len(history) == 1  # only the coord-bearing row
        assert history[0]["latitude"] == 37.77

    async def test_partial_coordinates_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155580105")
        session = await _create_session(db_session, user)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 40.7, "battery_level": 0.5},
        )
        assert response.status_code == 422

    async def test_empty_payload_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155580106")
        session = await _create_session(db_session, user)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={},
        )
        assert response.status_code == 422
