"""SOS is free, always — subscription gating applies only to check-in sessions.

Covers the 2026-07-02 flow-review decisions (docs/flow-review.md §4.2 A1,
§4.4.4): a panic press must never be blocked by billing state, and an SOS
session must not consume the single free-trial session.

Related: app/api/v1/endpoints/sessions.py (per-type gate),
app/api/v1/deps/auth.py (require_subscription_access),
app/services/subscription_service.py (get_sessions_used_count).
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.services.subscription_service import get_sessions_used_count
from tests.helpers import create_test_user


def _auth(user: User) -> dict:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


async def _add_circle_member(
    db: AsyncSession, owner: User, contact_phone: str
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


async def _exhaust_free_trial(db: AsyncSession, user: User) -> None:
    """Consume the single free-trial session with a completed check-in."""
    db.add(
        Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) - timedelta(hours=1),
            actual_return_time=datetime.now(UTC),
            status=SessionStatus.COMPLETED.value,
        )
    )
    await db.commit()


@pytest.mark.asyncio
class TestSOSBypassesSubscriptionGate:
    async def test_sos_succeeds_with_exhausted_trial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A user with no access (trial used, no subscription) can still SOS."""
        user = await create_test_user(
            db_session, phone_number="+14155580001", full_name="Trial Done"
        )
        await _add_circle_member(db_session, user, contact_phone="+14155580002")
        await _exhaust_free_trial(db_session, user)

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={"session_type": "sos"},
        )
        assert response.status_code == 201
        assert response.json()["session_type"] == "sos"

    async def test_checkin_still_gated_with_exhausted_trial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The subscription gate must still apply to check-in sessions."""
        user = await create_test_user(
            db_session, phone_number="+14155580003", full_name="Trial Done"
        )
        await _add_circle_member(db_session, user, contact_phone="+14155580004")
        await _exhaust_free_trial(db_session, user)

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat()
            },
        )
        assert response.status_code == 402
        assert response.headers.get("X-Subscription-Required") == "true"


@pytest.mark.asyncio
class TestSOSDoesNotConsumeFreeTrial:
    async def test_checkin_still_free_after_sos(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A new user's first SOS must not burn their free-trial session."""
        user = await create_test_user(
            db_session, phone_number="+14155580005", full_name="New User"
        )
        await _add_circle_member(db_session, user, contact_phone="+14155580006")

        sos = await client.post(
            "/api/v1/sessions", headers=_auth(user), json={"session_type": "sos"}
        )
        assert sos.status_code == 201

        # Complete the SOS so the check-in isn't blocked by the
        # one-active-session rule.
        complete = await client.put(
            f"/api/v1/sessions/{sos.json()['id']}/complete", headers=_auth(user)
        )
        assert complete.status_code == 200

        checkin = await client.post(
            "/api/v1/sessions",
            headers=_auth(user),
            json={
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat()
            },
        )
        assert checkin.status_code == 201

    async def test_sessions_used_count_excludes_sos(self, db_session: AsyncSession):
        """Only check-in sessions count toward the free trial."""
        user = await create_test_user(
            db_session, phone_number="+14155580007", full_name="Counter"
        )
        now = datetime.now(UTC)
        db_session.add_all(
            [
                Session(
                    user_id=user.id,
                    session_type=SessionType.SOS,
                    expected_return_time=now,
                    status=SessionStatus.COMPLETED.value,
                ),
                Session(
                    user_id=user.id,
                    session_type=SessionType.SOS,
                    expected_return_time=now,
                    status=SessionStatus.COMPLETED.value,
                ),
                Session(
                    user_id=user.id,
                    expected_return_time=now + timedelta(hours=1),
                    status=SessionStatus.COMPLETED.value,
                ),
            ]
        )
        await db_session.commit()

        assert await get_sessions_used_count(db_session, user.id) == 1
