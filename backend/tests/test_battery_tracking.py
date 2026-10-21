"""Tests for battery level tracking in session updates."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.services.session_tasks import _build_alert_content
from tests.helpers import create_test_user


async def _create_user(db: AsyncSession, phone_number: str) -> User:
    return await create_test_user(db, phone_number=phone_number, full_name="Test User")


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _create_session(
    db: AsyncSession,
    user: User,
    *,
    location_sharing: bool = True,
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
class TestBatteryTracking:
    async def test_location_update_with_battery(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155570100")
        session = await _create_session(db_session, user)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={
                "latitude": 40.7128,
                "longitude": -74.0060,
                "battery_level": 0.85,
                "battery_state": "unplugged",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["last_battery_level"] == 0.85
        assert data["last_battery_state"] == "unplugged"

    async def test_location_update_without_battery(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155570101")
        session = await _create_session(db_session, user)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 40.7128, "longitude": -74.0060},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["last_battery_level"] is None
        assert data["last_battery_state"] is None

    async def test_battery_in_location_history(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155570102")
        session = await _create_session(db_session, user)

        await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={
                "latitude": 40.7128,
                "longitude": -74.0060,
                "battery_level": 0.72,
                "battery_state": "charging",
            },
        )

        response = await client.get(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
        )
        assert response.status_code == 200
        points = response.json()
        assert len(points) == 1
        assert points[0]["battery_level"] == 0.72
        assert points[0]["battery_state"] == "charging"

    async def test_battery_level_validation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155570103")
        session = await _create_session(db_session, user)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={
                "latitude": 40.7128,
                "longitude": -74.0060,
                "battery_level": 1.5,
            },
        )
        assert response.status_code == 422

    async def test_battery_state_validation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155570104")
        session = await _create_session(db_session, user)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={
                "latitude": 40.7128,
                "longitude": -74.0060,
                "battery_state": "invalid_state",
            },
        )
        assert response.status_code == 422

    async def test_latest_battery_wins(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155570105")
        session = await _create_session(db_session, user)

        await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={
                "latitude": 40.7128,
                "longitude": -74.0060,
                "battery_level": 0.90,
                "battery_state": "charging",
            },
        )
        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={
                "latitude": 40.7129,
                "longitude": -74.0061,
                "battery_level": 0.45,
                "battery_state": "unplugged",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["last_battery_level"] == 0.45
        assert data["last_battery_state"] == "unplugged"

    async def test_battery_stored_regardless(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Battery has no sharing toggle — a sent reading is always stored
        # (guards against re-introducing a gate).
        user = await _create_user(db_session, "+14155570106")
        session = await _create_session(db_session, user)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={
                "latitude": 40.7128,
                "longitude": -74.0060,
                "battery_level": 0.85,
                "battery_state": "unplugged",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["last_battery_level"] == 0.85
        assert data["last_battery_state"] == "unplugged"

    async def test_session_response_includes_sharing_toggles(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155570107")
        await _create_session(db_session, user)

        response = await client.get(
            "/api/v1/sessions/active",
            headers=_auth(user),
        )
        assert response.status_code == 200
        data = response.json()
        assert data["location_sharing_enabled"] is True


@pytest.mark.asyncio
class TestBatteryAlertSuffix:
    # Battery rides along only when critically low (<5%) — a dying phone is
    # a safety signal, a half-full one is noise. See
    # session_tasks.LOW_BATTERY_ALERT_THRESHOLD.
    async def test_no_suffix_when_battery_above_threshold(
        self, db_session: AsyncSession
    ):
        user = await _create_user(db_session, "+14155570200")
        session = Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) + timedelta(hours=2),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)
        session.user = user
        session.last_battery_level = 0.50
        _, body = _build_alert_content(session)
        assert "battery" not in body.lower()

    async def test_suffix_when_battery_low(self, db_session: AsyncSession):
        user = await _create_user(db_session, "+14155570201")
        session = Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) + timedelta(hours=2),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)
        session.user = user
        session.last_battery_level = 0.03
        _, body = _build_alert_content(session)
        assert "Last known battery: 3%." in body
