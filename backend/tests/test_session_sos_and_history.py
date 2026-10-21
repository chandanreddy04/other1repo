"""Tests for SOS session creation and location history endpoint paths."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus
from app.models.subscription import (
    PlanType,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User
from tests.helpers import create_test_user


async def _create_user(
    db: AsyncSession, phone_number: str = "+14155551000", full_name: str = "Test User"
) -> User:
    return await create_test_user(db, phone_number=phone_number, full_name=full_name)


async def _create_subscribed_user(
    db: AsyncSession, phone_number: str = "+14155551000", full_name: str = "Sub User"
) -> User:
    user = await _create_user(db, phone_number=phone_number, full_name=full_name)
    sub = Subscription(
        user_id=user.id,
        phone_number_id=user.phone_number_id,
        plan_type=PlanType.MONTHLY,
        status=SubscriptionStatus.ACTIVE,
        source=SubscriptionSource.ADMIN,
        current_period_start=datetime.now(UTC),
        current_period_end=datetime.now(UTC) + timedelta(days=30),
    )
    db.add(sub)
    await db.commit()
    return user


def _auth(user: User) -> dict:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


async def _add_circle_member(
    db: AsyncSession, owner: User, contact_phone: str = "+14155570001"
) -> CircleOfTrustMember:
    contact = await create_test_user(
        db, phone_number=contact_phone, full_name="Circle Member"
    )
    member = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=contact.phone_number_id,
        nickname=contact.full_name,
        status=ContactStatus.ACTIVE.value,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


@pytest.mark.asyncio
class TestCreateSOSSession:
    async def test_create_sos_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155561000")
        await _add_circle_member(db_session, user, contact_phone="+14155571000")

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={"session_type": "sos"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["session_type"] == "sos"
        assert data["destination"] is None
        # SOS shares location + battery so the circle can find the person.
        assert data["location_sharing_enabled"] is True

    async def test_sos_with_location_shows_pin_on_the_alert_page(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # The last-known location the app attaches must reach the first alert:
        # the SOS dispatches inline, so the location is stored before dispatch.
        from uuid import UUID

        from sqlalchemy import select

        from app.models.alert import Alert

        user = await _create_user(db_session, phone_number="+14155561010")
        await _add_circle_member(db_session, user, contact_phone="+14155571010")

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={
                "session_type": "sos",
                "latitude": 40.785,
                "longitude": -73.968,
                "battery_level": 0.5,
            },
        )
        assert response.status_code == 201
        session_id = UUID(response.json()["id"])

        alert = (
            (
                await db_session.execute(
                    select(Alert).where(Alert.session_id == session_id)
                )
            )
            .scalars()
            .first()
        )
        assert alert is not None

        page = await client.get(f"/alerts/{alert.id}")
        assert "maps.google.com" in page.text  # the map pin is there
        assert "50%" in page.text  # battery shared too

    async def test_sos_without_location_still_fires(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # No location permission / no cached fix → SOS must still go out.
        user = await _create_user(db_session, phone_number="+14155561011")
        await _add_circle_member(db_session, user, contact_phone="+14155571011")
        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={"session_type": "sos"},
        )
        assert response.status_code == 201

    async def test_create_sos_session_no_circle(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155561001")

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={"session_type": "sos"},
        )
        assert response.status_code == 400
        assert "no active contacts" in response.json()["detail"].lower()

    async def test_create_checkin_session_no_circle(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155561002")

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=2)
                ).isoformat(),
            },
        )
        assert response.status_code == 400
        assert "circle" in response.json()["detail"].lower()


@pytest.mark.asyncio
class TestLocationHistory:
    async def test_location_history_as_owner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155561100")
        session = Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) + timedelta(hours=2),
            destination="Test",
            location_sharing_enabled=True,
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        response = await client.get(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_location_history_as_alert_recipient(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _create_user(db_session, phone_number="+14155561101")
        recipient = await _create_user(db_session, phone_number="+14155561102")
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC) + timedelta(hours=2),
            destination="Test",
            location_sharing_enabled=True,
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        alert = Alert(
            session_id=session.id,
            sent_to_user_id=recipient.id,
            alert_type=AlertType.MISSED_SESSION.value,
            status=AlertStatus.SENT.value,
            message="Alert",
            sent_at=datetime.now(UTC),
        )
        db_session.add(alert)
        await db_session.commit()

        response = await client.get(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(recipient),
        )
        assert response.status_code == 200

    async def test_location_history_unauthorized(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _create_user(db_session, phone_number="+14155561103")
        stranger = await _create_user(db_session, phone_number="+14155561104")
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC) + timedelta(hours=2),
            destination="Test",
            location_sharing_enabled=True,
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        response = await client.get(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(stranger),
        )
        assert response.status_code == 403

    async def test_location_history_not_found(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155561105")
        fake_id = uuid.uuid4()

        response = await client.get(
            f"/api/v1/sessions/{fake_id}/locations",
            headers=_auth(user),
        )
        assert response.status_code == 404


@pytest.mark.asyncio
class TestCompleteMissedWithAllClear:
    async def test_complete_missed_sends_all_clear(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155561200")
        await _add_circle_member(db_session, user, contact_phone="+14155571200")
        session = Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) - timedelta(hours=1),
            status=SessionStatus.MISSED.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        with patch(
            "app.services.notification_helpers.send_all_clear_to_circle",
            new_callable=AsyncMock,
        ) as mock_all_clear:
            response = await client.put(
                f"/api/v1/sessions/{session.id}/complete",
                headers=_auth(user),
            )
            assert response.status_code == 200
            mock_all_clear.assert_called_once()
