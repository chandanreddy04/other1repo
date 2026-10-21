"""Tests for safety constraints (Commit 2).

- Disallow circle add/remove during active session
- Require circle members for check-in session creation
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus, SessionType
from app.models.subscription import (
    PlanType,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User
from tests.helpers import create_test_user


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _subscribed_user(db: AsyncSession, phone_number: str) -> User:
    user = await create_test_user(db, phone_number=phone_number)
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


async def _active_circle_member(
    db: AsyncSession, owner: User, phone: str = "+14155558881"
) -> CircleOfTrustMember:
    contact = await create_test_user(db, phone_number=phone, full_name="Buddy")
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


async def _active_session(db: AsyncSession, user: User) -> Session:
    session = Session(
        user_id=user.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        status=SessionStatus.ACTIVE.value,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@pytest.mark.asyncio
class TestCircleChangesBlockedDuringActiveSession:
    async def test_add_circle_blocked_during_active_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155558001")
        await _active_session(db_session, user)

        response = await client.post(
            "/api/v1/circle/members",
            headers=_auth(user),
            json={
                "nickname": "New Contact",
                "contact_phone_number": "+14155558010",
            },
        )
        assert response.status_code == 409
        assert "active" in response.json()["detail"].lower()

    async def test_remove_circle_blocked_during_active_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155558002")
        member = await _active_circle_member(db_session, user, "+14155558011")
        await _active_session(db_session, user)

        response = await client.delete(
            f"/api/v1/circle/members/{member.id}", headers=_auth(user)
        )
        assert response.status_code == 409

    async def test_add_circle_allowed_when_no_active_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155558003")

        response = await client.post(
            "/api/v1/circle/members",
            headers=_auth(user),
            json={
                "nickname": "New Contact",
                "contact_phone_number": "+14155558012",
            },
        )
        assert response.status_code == 200

    async def test_completed_session_does_not_block_circle_changes(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155558004")
        # Completed session should not block
        session = Session(
            user_id=user.id,
            session_type=SessionType.CHECKIN.value,
            expected_return_time=datetime.now(UTC) - timedelta(hours=1),
            status=SessionStatus.COMPLETED.value,
        )
        db_session.add(session)
        await db_session.commit()

        response = await client.post(
            "/api/v1/circle/members",
            headers=_auth(user),
            json={
                "nickname": "New Contact",
                "contact_phone_number": "+14155558013",
            },
        )
        assert response.status_code == 200


@pytest.mark.asyncio
class TestSessionRequiresCircle:
    async def test_create_session_blocked_with_no_circle(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _subscribed_user(db_session, phone_number="+14155558005")

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat(),
                "destination": "Park",
            },
        )
        assert response.status_code == 400
        assert "circle" in response.json()["detail"].lower()

    async def test_create_session_succeeds_with_active_circle(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _subscribed_user(db_session, phone_number="+14155558006")
        await _active_circle_member(db_session, user, phone="+14155558020")

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat(),
                "destination": "Park",
            },
        )
        assert response.status_code == 201

    async def test_create_session_blocked_with_only_pending_circle_members(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _subscribed_user(db_session, phone_number="+14155558007")
        contact = await create_test_user(db_session, phone_number="+14155558021")
        member = CircleOfTrustMember(
            user_id=user.id,
            contact_phone_number_id=contact.phone_number_id,
            nickname="Pending Contact",
            status=ContactStatus.PENDING.value,
        )
        db_session.add(member)
        await db_session.commit()

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat(),
                "destination": "Park",
            },
        )
        assert response.status_code == 400
