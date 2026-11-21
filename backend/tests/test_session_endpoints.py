"""Tests for session and alert endpoint code paths."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from dateutil.parser import isoparse
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    phone_number: str = "+14155551000",
    full_name: str = "Test User",
) -> User:
    """Create a verified, active user."""
    return await create_test_user(db, phone_number=phone_number, full_name=full_name)


async def _create_subscribed_user(
    db: AsyncSession,
    phone_number: str = "+14155551000",
    full_name: str = "Subscribed User",
) -> User:
    """Create a user with an active subscription."""
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
    """Return auth headers for a user."""
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


async def _add_circle_member(
    db: AsyncSession,
    owner: User,
    contact_phone: str = "+14155570001",
) -> CircleOfTrustMember:
    """Attach an active circle member to the owner (required for session creation)."""
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


async def _create_active_session(
    db: AsyncSession,
    user: User,
    *,
    status: str = SessionStatus.ACTIVE.value,
    location_sharing: bool = False,
    destination: str | None = "Test Destination",
    hours_ahead: int = 2,
) -> Session:
    """Insert a session directly in the database."""
    session = Session(
        user_id=user.id,
        expected_return_time=datetime.now(UTC) + timedelta(hours=hours_ahead),
        destination=destination,
        location_sharing_enabled=location_sharing,
        status=status,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _create_alert(
    db: AsyncSession,
    session: Session,
    sent_to_user: User,
    *,
    alert_type: AlertType = AlertType.MISSED_SESSION,
    status: AlertStatus = AlertStatus.SENT,
) -> Alert:
    """Insert an alert directly in the database."""
    alert = Alert(
        session_id=session.id,
        sent_to_user_id=sent_to_user.id,
        alert_type=alert_type.value,
        status=status.value,
        message="Test alert",
        sent_at=datetime.now(UTC),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


# ---------------------------------------------------------------------------
# GET /sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSessions:
    async def test_list_sessions_empty(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560100")
        response = await client.get("/api/v1/sessions", headers=_auth(user))
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_sessions_returns_user_sessions(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560101")
        s1 = await _create_active_session(db_session, user, destination="Place A")
        s2 = await _create_active_session(db_session, user, destination="Place B")

        response = await client.get("/api/v1/sessions", headers=_auth(user))
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        returned_ids = {item["id"] for item in data}
        assert str(s1.id) in returned_ids
        assert str(s2.id) in returned_ids

    async def test_list_sessions_pagination_skip(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560102")
        for i in range(5):
            await _create_active_session(db_session, user, destination=f"Place {i}")

        response = await client.get(
            "/api/v1/sessions?skip=3&limit=10", headers=_auth(user)
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_sessions_pagination_limit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560103")
        for i in range(5):
            await _create_active_session(db_session, user, destination=f"Place {i}")

        response = await client.get("/api/v1/sessions?limit=2", headers=_auth(user))
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_sessions_pagination_skip_and_limit(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560104")
        for i in range(5):
            await _create_active_session(db_session, user, destination=f"D{i}")

        response = await client.get(
            "/api/v1/sessions?skip=2&limit=2", headers=_auth(user)
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_sessions_does_not_return_other_users_sessions(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user_a = await _create_user(db_session, phone_number="+14155560105")
        user_b = await _create_user(db_session, phone_number="+14155560106")
        await _create_active_session(db_session, user_b, destination="Other place")

        response = await client.get("/api/v1/sessions", headers=_auth(user_a))
        assert response.status_code == 200
        assert response.json() == []


# ---------------------------------------------------------------------------
# GET /sessions/active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetActiveSession:
    async def test_active_session_exists(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560200")
        session = await _create_active_session(db_session, user)

        response = await client.get("/api/v1/sessions/active", headers=_auth(user))
        assert response.status_code == 200
        data = response.json()
        assert data is not None
        assert data["id"] == str(session.id)
        assert data["status"] == "active"

    async def test_no_active_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560201")
        response = await client.get("/api/v1/sessions/active", headers=_auth(user))
        assert response.status_code == 200
        assert response.json() is None

    async def test_completed_session_not_returned_as_active(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560202")
        session = await _create_active_session(db_session, user)
        session.status = SessionStatus.COMPLETED.value
        session.actual_return_time = datetime.now(UTC)
        await db_session.commit()

        response = await client.get("/api/v1/sessions/active", headers=_auth(user))
        assert response.status_code == 200
        assert response.json() is None


# ---------------------------------------------------------------------------
# POST /sessions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateSession:
    async def test_create_session_with_free_trial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """New user can create a session via free trial."""
        user = await _create_user(db_session, phone_number="+14155560300")
        await _add_circle_member(db_session, user, contact_phone="+14155570300")

        session_data = {
            "expected_return_time": (
                datetime.now(UTC) + timedelta(hours=2)
            ).isoformat(),
            "destination": "Coffee Shop",
            "location_sharing_enabled": False,
        }
        response = await client.post(
            "/api/v1/sessions", headers=_auth(user), json=session_data
        )
        assert response.status_code == 201
        data = response.json()
        assert data["destination"] == "Coffee Shop"
        assert data["status"] == "active"

    async def test_create_session_with_subscription(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Subscribed user can create sessions."""
        user = await _create_subscribed_user(db_session, phone_number="+14155560301")
        await _add_circle_member(db_session, user, contact_phone="+14155570301")

        session_data = {
            "expected_return_time": (
                datetime.now(UTC) + timedelta(hours=1)
            ).isoformat(),
            "destination": "Gym",
        }
        response = await client.post(
            "/api/v1/sessions", headers=_auth(user), json=session_data
        )
        assert response.status_code == 201
        assert response.json()["destination"] == "Gym"

    async def test_create_session_past_return_time(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Return time must be at least the minimum lead from now
        (owner decision 2026-11-19: never < 5 minutes)."""
        user = await _create_user(db_session, phone_number="+14155560302")

        for offset in (-timedelta(hours=1), timedelta(minutes=2)):
            session_data = {
                "expected_return_time": (datetime.now(UTC) + offset).isoformat(),
                "destination": "Too Soon Trip",
            }
            response = await client.post(
                "/api/v1/sessions", headers=_auth(user), json=session_data
            )
            assert response.status_code == 400
            assert "5 minutes" in response.json()["detail"]

    async def test_create_session_already_active(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Cannot create a second session while one is active."""
        user = await _create_subscribed_user(db_session, phone_number="+14155560303")
        await _create_active_session(db_session, user)

        session_data = {
            "expected_return_time": (
                datetime.now(UTC) + timedelta(hours=1)
            ).isoformat(),
        }
        response = await client.post(
            "/api/v1/sessions", headers=_auth(user), json=session_data
        )
        assert response.status_code == 400
        assert "active session" in response.json()["detail"].lower()

    async def test_create_session_no_subscription_no_trial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User with exhausted free trial and no subscription is denied."""
        user = await _create_user(db_session, phone_number="+14155560304")
        # Consume free trial by creating a completed session
        db_session.add(
            Session(
                user_id=user.id,
                expected_return_time=datetime.now(UTC) - timedelta(hours=1),
                actual_return_time=datetime.now(UTC),
                status=SessionStatus.COMPLETED.value,
            )
        )
        await db_session.commit()

        session_data = {
            "expected_return_time": (
                datetime.now(UTC) + timedelta(hours=1)
            ).isoformat(),
        }
        response = await client.post(
            "/api/v1/sessions", headers=_auth(user), json=session_data
        )
        assert response.status_code == 402

    async def test_create_minimal_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Session with only required fields."""
        user = await _create_user(db_session, phone_number="+14155560305")
        await _add_circle_member(db_session, user, contact_phone="+14155570305")
        payload = {
            "expected_return_time": (
                datetime.now(UTC) + timedelta(hours=1)
            ).isoformat(),
        }
        response = await client.post(
            "/api/v1/sessions", headers=_auth(user), json=payload
        )
        assert response.status_code == 201
        data = response.json()
        assert data["destination"] is None
        assert data["location_sharing_enabled"] is False

    async def test_create_session_with_location_sharing(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Session with location sharing enabled."""
        user = await _create_user(db_session, phone_number="+14155560306")
        await _add_circle_member(db_session, user, contact_phone="+14155570306")
        payload = {
            "expected_return_time": (
                datetime.now(UTC) + timedelta(hours=3)
            ).isoformat(),
            "destination": "Night Out",
            "location_sharing_enabled": True,
        }
        response = await client.post(
            "/api/v1/sessions", headers=_auth(user), json=payload
        )
        assert response.status_code == 201
        assert response.json()["location_sharing_enabled"] is True


# ---------------------------------------------------------------------------
# PUT /sessions/{id}/complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCompleteSession:
    async def test_complete_session_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560400")
        session = await _create_active_session(db_session, user)

        response = await client.put(
            f"/api/v1/sessions/{session.id}/complete", headers=_auth(user)
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["actual_return_time"] is not None

    async def test_complete_session_not_active(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Completing an already-completed session returns 400."""
        user = await _create_user(db_session, phone_number="+14155560401")
        session = await _create_active_session(db_session, user)
        session.status = SessionStatus.COMPLETED.value
        session.actual_return_time = datetime.now(UTC)
        await db_session.commit()

        response = await client.put(
            f"/api/v1/sessions/{session.id}/complete", headers=_auth(user)
        )
        assert response.status_code == 400
        assert "cannot be completed" in response.json()["detail"].lower()

    async def test_complete_session_not_found(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560402")
        fake_id = uuid.uuid4()
        response = await client.put(
            f"/api/v1/sessions/{fake_id}/complete", headers=_auth(user)
        )
        assert response.status_code == 404

    async def test_complete_session_other_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Cannot complete another user's session."""
        owner = await _create_user(db_session, phone_number="+14155560403")
        other = await _create_user(db_session, phone_number="+14155560404")
        session = await _create_active_session(db_session, owner)

        response = await client.put(
            f"/api/v1/sessions/{session.id}/complete", headers=_auth(other)
        )
        assert response.status_code == 403

    async def test_complete_missed_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Completing a missed session marks it completed (user is safe)."""
        user = await _create_user(db_session, phone_number="+14155560405")
        session = await _create_active_session(db_session, user)
        session.status = SessionStatus.MISSED.value
        await db_session.commit()

        response = await client.put(
            f"/api/v1/sessions/{session.id}/complete", headers=_auth(user)
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["actual_return_time"] is not None

    async def test_complete_missed_session_resolves_alerts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Completing a missed session resolves outstanding alerts."""
        user = await _create_user(db_session, phone_number="+14155560406")
        circle_user = await _create_user(db_session, phone_number="+14155560407")
        circle_user2 = await _create_user(db_session, phone_number="+14155560408")
        session = await _create_active_session(db_session, user)
        session.status = SessionStatus.MISSED.value
        await db_session.commit()

        # Two circle members on the same session — one resolvable, one already
        # acknowledged (distinct recipients per uq_alerts_session_recipient_type).
        alert = await _create_alert(
            db_session, session, circle_user, status=AlertStatus.SENT
        )
        acked_alert = await _create_alert(
            db_session, session, circle_user2, status=AlertStatus.ACKNOWLEDGED
        )

        response = await client.put(
            f"/api/v1/sessions/{session.id}/complete", headers=_auth(user)
        )
        assert response.status_code == 200

        await db_session.refresh(alert)
        await db_session.refresh(acked_alert)
        assert alert.status == AlertStatus.RESOLVED.value
        assert alert.resolved_at is not None
        assert acked_alert.status == AlertStatus.ACKNOWLEDGED.value
        assert acked_alert.resolved_at is None

    async def test_complete_alerted_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Completing an ALERTED session (alerts dispatched) marks it completed and resolves alerts."""
        user = await _create_user(db_session, phone_number="+14155560409")
        circle_user = await _create_user(db_session, phone_number="+14155560410")
        session = await _create_active_session(db_session, user)
        session.status = SessionStatus.ALERTED.value
        await db_session.commit()

        alert = await _create_alert(
            db_session, session, circle_user, status=AlertStatus.SENT
        )

        response = await client.put(
            f"/api/v1/sessions/{session.id}/complete", headers=_auth(user)
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

        await db_session.refresh(alert)
        assert alert.status == AlertStatus.RESOLVED.value

    async def test_complete_cancelled_session_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Completing a cancelled session returns 400."""
        user = await _create_user(db_session, phone_number="+14155560408")
        session = await _create_active_session(db_session, user)
        session.status = SessionStatus.CANCELLED.value
        await db_session.commit()

        response = await client.put(
            f"/api/v1/sessions/{session.id}/complete", headers=_auth(user)
        )
        assert response.status_code == 400
        assert "cannot be completed" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# PUT /sessions/{id}/extend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExtendSession:
    async def test_extend_session_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560500")
        session = await _create_active_session(db_session, user, hours_ahead=2)
        original_return_time = session.expected_return_time

        response = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": 60},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"
        new_return = isoparse(data["expected_return_time"])
        expected = original_return_time + timedelta(minutes=60)
        assert abs((new_return - expected).total_seconds()) < 2

    async def test_extend_session_not_active(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Extending a completed session returns 400."""
        user = await _create_user(db_session, phone_number="+14155560501")
        session = await _create_active_session(db_session, user)
        session.status = SessionStatus.COMPLETED.value
        session.actual_return_time = datetime.now(UTC)
        await db_session.commit()

        response = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": 30},
        )
        assert response.status_code == 400
        assert "not active" in response.json()["detail"].lower()

    async def test_extend_session_not_found(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560502")
        fake_id = uuid.uuid4()
        response = await client.put(
            f"/api/v1/sessions/{fake_id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": 30},
        )
        assert response.status_code == 404

    async def test_extend_session_other_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Cannot extend another user's session."""
        owner = await _create_user(db_session, phone_number="+14155560503")
        other = await _create_user(db_session, phone_number="+14155560504")
        session = await _create_active_session(db_session, owner)

        response = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(other),
            json={"minutes_to_extend": 30},
        )
        assert response.status_code == 403

    async def test_extend_session_invalid_minutes_zero(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560505")
        session = await _create_active_session(db_session, user)

        response = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": 0},
        )
        assert response.status_code == 422

    async def test_extend_session_invalid_minutes_over_max(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560506")
        session = await _create_active_session(db_session, user)

        response = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": 300},
        )
        assert response.status_code == 422

    async def test_extend_missed_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Extending a missed session returns 400."""
        user = await _create_user(db_session, phone_number="+14155560507")
        session = await _create_active_session(db_session, user)
        session.status = SessionStatus.MISSED.value
        await db_session.commit()

        response = await client.put(
            f"/api/v1/sessions/{session.id}/extend",
            headers=_auth(user),
            json={"minutes_to_extend": 30},
        )
        assert response.status_code == 400
        assert "not active" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# POST /sessions/{id}/locations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateLocation:
    async def test_update_location_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560600")
        session = await _create_active_session(db_session, user, location_sharing=True)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 40.7128, "longitude": -74.0060},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["last_known_latitude"] == 40.7128
        assert data["last_known_longitude"] == -74.0060
        assert data["last_location_update"] is not None

    async def test_update_location_sharing_disabled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560601")
        session = await _create_active_session(db_session, user, location_sharing=False)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 40.7128, "longitude": -74.0060},
        )
        assert response.status_code == 400
        assert "not enabled" in response.json()["detail"].lower()

    async def test_update_location_not_found(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560602")
        fake_id = uuid.uuid4()
        response = await client.post(
            f"/api/v1/sessions/{fake_id}/locations",
            headers=_auth(user),
            json={"latitude": 40.7128, "longitude": -74.0060},
        )
        assert response.status_code == 404

    async def test_update_location_other_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _create_user(db_session, phone_number="+14155560603")
        other = await _create_user(db_session, phone_number="+14155560604")
        session = await _create_active_session(db_session, owner, location_sharing=True)

        response = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(other),
            json={"latitude": 40.7128, "longitude": -74.0060},
        )
        assert response.status_code == 403

    async def test_update_location_multiple_times(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Location can be updated more than once."""
        user = await _create_user(db_session, phone_number="+14155560605")
        session = await _create_active_session(db_session, user, location_sharing=True)

        resp1 = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 37.0, "longitude": -122.0},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            f"/api/v1/sessions/{session.id}/locations",
            headers=_auth(user),
            json={"latitude": 38.0, "longitude": -121.0},
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["last_known_latitude"] == 38.0
        assert data["last_known_longitude"] == -121.0


# ---------------------------------------------------------------------------
# POST /sessions/outfit-photos
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUploadOutfitPhoto:
    async def test_upload_outfit_session_not_found(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _create_user(db_session, phone_number="+14155560700")
        fake_id = uuid.uuid4()

        resp = await client.post(
            "/api/v1/sessions/outfit-photos",
            headers=_auth(user),
            data={"session_id": str(fake_id)},
            files={
                "file": ("photo.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg")
            },
        )
        assert resp.status_code == 404

    async def test_upload_outfit_other_users_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _create_user(db_session, phone_number="+14155560701")
        other = await _create_user(db_session, phone_number="+14155560702")
        session = await _create_active_session(db_session, owner)

        resp = await client.post(
            "/api/v1/sessions/outfit-photos",
            headers=_auth(other),
            data={"session_id": str(session.id)},
            files={
                "file": ("photo.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, "image/jpeg")
            },
        )
        assert resp.status_code == 403

    async def test_upload_outfit_invalid_image(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Uploading an invalid file triggers validation or error handler."""
        user = await _create_user(db_session, phone_number="+14155560703")
        session = await _create_active_session(db_session, user)

        resp = await client.post(
            "/api/v1/sessions/outfit-photos",
            headers=_auth(user),
            data={"session_id": str(session.id)},
            files={"file": ("photo.txt", b"not an image at all", "text/plain")},
        )
        assert resp.status_code in (400, 422, 500)
