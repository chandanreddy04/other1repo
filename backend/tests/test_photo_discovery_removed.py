"""Background photo discovery is removed (owner decision 2026-09-05).

The mobile app used to poll the camera roll during a session and upload every
new photo to POST /sessions/{id}/photos for the circle's alert page. That whole
pipeline — the session_photos table, its endpoints, the admin gallery, the
public-page photo grid and the photo_sharing_enabled toggle — is gone. The
outfit photo and the profile picture are untouched.

These tests pin the contract so the feature can't quietly grow back, and so
clients still running the old app (which send the removed field and call the
removed routes) keep working.

Related: app/schemas/session.py, app/services/session_tasks.py
(purge_session_data), app/web/admin_registry.py, app/web/routes_web.py,
alembic/versions/20260905_1628-d75a707d6ba9_*.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.models.subscription import (
    PlanType,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User
from app.services.session_tasks import purge_session_data
from tests.helpers import create_test_user

_PHONE = iter(f"+141555980{n:02d}" for n in range(1, 99))


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _owner_with_circle(db: AsyncSession, *, subscribed: bool) -> User:
    owner = await create_test_user(db, phone_number=next(_PHONE), full_name="Ana Owner")
    contact = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Cody Contact"
    )
    db.add(
        CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=contact.phone_number_id,
            nickname=contact.full_name,
            status=ContactStatus.ACTIVE.value,
        )
    )
    if subscribed:
        db.add(
            Subscription(
                user_id=owner.id,
                phone_number_id=owner.phone_number_id,
                plan_type=PlanType.MONTHLY,
                status=SubscriptionStatus.ACTIVE,
                source=SubscriptionSource.ADMIN,
                current_period_start=datetime.now(UTC),
                current_period_end=datetime.now(UTC) + timedelta(days=30),
            )
        )
    await db.commit()
    return owner


@pytest.mark.asyncio
class TestOldClientsKeepWorking:
    async def test_legacy_photo_sharing_field_is_ignored_on_create(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # The shipped app still sends photo_sharing_enabled on every check-in.
        # It must be dropped silently (201), never a 422, and never echoed.
        owner = await _owner_with_circle(db_session, subscribed=True)
        resp = await client.post(
            "/api/v1/sessions",
            headers=_auth(owner),
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=2)
                ).isoformat(),
                "destination": "Central Park",
                "location_sharing_enabled": True,
                "photo_sharing_enabled": True,
            },
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["location_sharing_enabled"] is True
        assert "photo_sharing_enabled" not in data

    async def test_sos_response_has_no_photo_sharing_field(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner_with_circle(db_session, subscribed=False)
        resp = await client.post(
            "/api/v1/sessions", headers=_auth(owner), json={"session_type": "sos"}
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["location_sharing_enabled"] is True
        assert "photo_sharing_enabled" not in data

    async def test_session_photo_routes_are_gone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner_with_circle(db_session, subscribed=False)
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()

        listing = await client.get(
            f"/api/v1/sessions/{session.id}/photos", headers=_auth(owner)
        )
        assert listing.status_code == 404
        # The outfit photo route (kept) still exists — a bad upload is a 4xx
        # from the route itself, not a routing 404.
        outfit = await client.post(
            "/api/v1/sessions/outfit-photos",
            headers=_auth(owner),
            data={"session_id": str(session.id)},
        )
        assert outfit.status_code == 422


@pytest.mark.asyncio
class TestServerSurfacesHaveNoDiscoveredPhotos:
    async def test_purge_counts_only_outfit_photo_and_locations(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(db_session, phone_number=next(_PHONE))
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC) - timedelta(hours=3),
            status=SessionStatus.COMPLETED.value,
            outfit_photo_url="https://bkt.s3.us-west-2.amazonaws.com/outfit-photos/o.jpg",
        )
        db_session.add(session)
        await db_session.commit()
        db_session.add(
            SessionUpdate(
                session_id=session.id,
                latitude=40.7,
                longitude=-73.9,
                recorded_at=datetime.now(UTC),
            )
        )
        await db_session.commit()

        blob = MagicMock()
        blob.delete_file = AsyncMock(return_value=True)
        counts = await purge_session_data(db_session, session, blob)

        assert counts == {"photos_deleted": 1, "locations_deleted": 1}
        blob.delete_file.assert_awaited_once_with("outfit-photos/o.jpg")

    async def test_admin_session_detail_has_no_captured_photos_section(
        self, client: AsyncClient, db_session: AsyncSession, admin_cookies: dict
    ):
        owner = await create_test_user(db_session, phone_number=next(_PHONE))
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC),
            status=SessionStatus.ACTIVE.value,
            outfit_photo_url="https://example.com/outfit.jpg",
        )
        db_session.add(session)
        await db_session.commit()

        resp = await client.get(f"/admin/sessions/{session.id}", cookies=admin_cookies)
        assert resp.status_code == 200
        assert "Outfit photo" in resp.text
        assert "Captured photos" not in resp.text
        assert "Photo Sharing" not in resp.text

    async def test_public_alert_page_has_no_shared_photo_grid(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number=next(_PHONE), full_name="Ana Owner"
        )
        contact = await create_test_user(
            db_session, phone_number=next(_PHONE), full_name="Cody Contact"
        )
        session = Session(
            user_id=owner.id,
            expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
            destination="Central Park",
            status=SessionStatus.MISSED.value,
            tz_offset_minutes=0,
        )
        db_session.add(session)
        await db_session.commit()
        alert = Alert(
            session_id=session.id,
            sent_to_phone_id=contact.phone_number_id,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
            message="test",
        )
        db_session.add(alert)
        await db_session.commit()
        await db_session.refresh(alert)

        resp = await client.get(f"/alerts/{alert.id}")
        assert resp.status_code == 200
        assert "Central Park" in resp.text
        assert "Photos Ana shared" not in resp.text
        assert "photo-grid" not in resp.text
