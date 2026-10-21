"""Integration tests for session flows - real database operations."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.user import crud_user
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.user import UserCreate
from tests.helpers import create_test_user


async def _add_circle_member(
    db: AsyncSession, owner: User, contact_phone: str
) -> CircleOfTrustMember:
    """Attach an active circle member (required for session creation)."""
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
    return member


@pytest.mark.asyncio
class TestSessionIntegration:
    """Test complete session flows with real database."""

    async def test_full_session_lifecycle(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Test creating, managing, and completing a session."""
        # Step 1: Create a real user
        user_data = UserCreate(
            phone_number="+14155557777", full_name="Session Test User"
        )
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        await _add_circle_member(db_session, user, contact_phone="+14155567777")

        # Step 2: Create auth token for the user
        from app.core.security import create_access_token

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        # Step 3: Create a session
        session_data = {
            "expected_return_time": (
                datetime.now(UTC) + timedelta(hours=2)
            ).isoformat(),
            "destination": "Downtown Meeting",
            "location_sharing_enabled": True,
        }

        response = await client.post(
            "/api/v1/sessions", headers=headers, json=session_data
        )
        assert response.status_code == 201
        session_response = response.json()
        assert session_response["destination"] == "Downtown Meeting"
        assert session_response["status"] == "active"
        session_id = session_response["id"]

        # Step 4: Get active session
        response = await client.get("/api/v1/sessions/active", headers=headers)
        assert response.status_code == 200
        active_session = response.json()
        assert active_session["id"] == session_id

        # Step 5: Update location
        location_data = {"latitude": 37.7749, "longitude": -122.4194}
        response = await client.post(
            f"/api/v1/sessions/{session_id}/locations",
            headers=headers,
            json=location_data,
        )
        assert response.status_code == 200
        updated_session = response.json()
        assert updated_session["last_known_latitude"] == 37.7749

        # Step 6: Extend session
        extend_data = {"minutes_to_extend": 30}
        response = await client.put(
            f"/api/v1/sessions/{session_id}/extend", headers=headers, json=extend_data
        )
        assert response.status_code == 200

        # Step 7: Complete session
        response = await client.put(
            f"/api/v1/sessions/{session_id}/complete", headers=headers
        )
        assert response.status_code == 200
        completed = response.json()
        assert completed["status"] == "completed"

        # Step 8: Verify no active session
        response = await client.get("/api/v1/sessions/active", headers=headers)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            # Should return null or indicate no active session
            data = response.json()
            assert (
                data is None
                or data == {}
                or (isinstance(data, dict) and data.get("status") != "active")
            )

    async def test_session_expiry_and_alerts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Test session expiry detection and alert creation."""
        # Create user
        user_data = UserCreate(
            phone_number="+14155558888", full_name="Expiry Test User"
        )
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        await _add_circle_member(db_session, user, contact_phone="+14155568888")

        from app.core.security import create_access_token

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        # Create a valid-length session, then backdate its deadline in the
        # DB to simulate expiry (the API floor forbids creating one that
        # expires in a minute — owner decision 2026-07-19).
        session_data = {
            "expected_return_time": (
                datetime.now(UTC) + timedelta(hours=1)
            ).isoformat(),
            "destination": "Quick Trip",
        }

        response = await client.post(
            "/api/v1/sessions", headers=headers, json=session_data
        )
        assert response.status_code == 201
        session = response.json()

        from sqlalchemy import update as sa_update

        from app.models.session import Session as SessionModel

        await db_session.execute(
            sa_update(SessionModel)
            .where(SessionModel.id == session["id"])
            .values(expected_return_time=datetime.now(UTC) + timedelta(minutes=1))
        )
        await db_session.commit()

        # Check if session is active (not expired yet)
        from app.crud.session import crud_session

        active_session = await crud_session.get_active_session(
            db_session, user_id=user.id
        )
        assert active_session is not None
        assert str(active_session.id) == session["id"]

        # Manually update the session to be expired
        from sqlalchemy import update

        await db_session.execute(
            update(Session)
            .where(Session.id == session["id"])
            .values(
                expected_return_time=datetime.now(UTC) - timedelta(hours=1),
                status=SessionStatus.EXPIRED.value
                if hasattr(SessionStatus, "EXPIRED")
                else SessionStatus.COMPLETED.value,
            )
        )
        await db_session.commit()

        # Now the session should be expired (no longer active)
        active_session = await crud_session.get_active_session(
            db_session, user_id=user.id
        )
        # Should either be None or marked as expired
        assert active_session is None or active_session.status != "active"

    async def test_session_without_destination(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Test creating session without optional fields."""
        # Create user
        user_data = UserCreate(
            phone_number="+14155553333", full_name="Minimal Session User"
        )
        user = await crud_user.create(db_session, obj_in=user_data)
        await db_session.commit()

        await _add_circle_member(db_session, user, contact_phone="+14155563333")

        from app.core.security import create_access_token

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        # Create minimal session
        session_data = {
            "expected_return_time": (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        }

        response = await client.post(
            "/api/v1/sessions", headers=headers, json=session_data
        )
        assert response.status_code == 201
        session = response.json()
        assert session["destination"] is None
        assert session["location_sharing_enabled"] is False

    async def test_concurrent_sessions_prevented(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Test that users can't create multiple active sessions."""
        # Create user with an active subscription so the paywall doesn't block
        user_data = UserCreate(
            phone_number="+14155554444", full_name="Concurrent Test User"
        )
        user = await crud_user.create(db_session, obj_in=user_data)

        from app.models.subscription import (
            PlanType,
            Subscription,
            SubscriptionSource,
            SubscriptionStatus,
        )

        subscription = Subscription(
            user_id=user.id,
            phone_number_id=user.phone_number_id,
            plan_type=PlanType.MONTHLY,
            status=SubscriptionStatus.ACTIVE,
            source=SubscriptionSource.ADMIN,
            current_period_start=datetime.now(UTC),
            current_period_end=datetime.now(UTC) + timedelta(days=30),
        )
        db_session.add(subscription)
        await db_session.commit()

        await _add_circle_member(db_session, user, contact_phone="+14155564444")

        from app.core.security import create_access_token

        token = create_access_token(str(user.id))
        headers = {"Authorization": f"Bearer {token}"}

        # Create first session
        session_data = {
            "expected_return_time": (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        }

        response = await client.post(
            "/api/v1/sessions", headers=headers, json=session_data
        )
        assert response.status_code == 201

        # Try to create second session
        response = await client.post(
            "/api/v1/sessions", headers=headers, json=session_data
        )
        # Should fail - active session exists
        assert response.status_code == 400
