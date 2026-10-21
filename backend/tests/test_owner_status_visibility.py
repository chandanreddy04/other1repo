"""Owner poll visibility: /sessions/active returns non-terminal sessions
(ACTIVE, MISSED, ALERTED) with the server-truth flags, and circle_unreachable
is computed from delivery terminal states.

A MISSED/ALERTED session is a live incident: the mobile store reloads from
/sessions/active on every mount, so excluding escalated sessions would erase
the owner's escalation UI and end the Live Activity mid-incident (that was a
real bug — the store even had dead missed/alerted branches waiting for this).
circle_unreachable is the honest replacement for an indefinite "Notifying your
circle…" when every delivery is terminally undeliverable.

Related: app/crud/session.py::get_active_session,
app/api/v1/endpoints/sessions.py::_with_owner_status_flags,
app/services/notification_outbox.py::is_circle_unreachable.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus
from app.models.subscription import (
    PlanType,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User
from tests.helpers import create_test_user

_PHONE = iter(f"+141555980{n:02d}" for n in range(1, 99))


def _auth(user: User) -> dict:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


async def _owner(db: AsyncSession) -> User:
    return await create_test_user(
        db, phone_number=next(_PHONE), full_name="Olive Owner"
    )


async def _add_member(db: AsyncSession, owner: User) -> CircleOfTrustMember:
    contact = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Cara Contact"
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


async def _session(
    db: AsyncSession,
    owner: User,
    *,
    status: str,
    minutes_offset: int = -30,
) -> Session:
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) + timedelta(minutes=minutes_offset),
        destination="The Pier",
        status=status,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


def _delivery(
    session: Session, owner: User, status: DeliveryStatus
) -> NotificationDelivery:
    return NotificationDelivery(
        dedupe_key=str(uuid.uuid4()),
        kind=NotificationKind.CIRCLE_ALERT,
        channel=DeliveryChannel.SMS,
        next_attempt_at=datetime.now(UTC),
        body="alert",
        status=status,
        session_id=session.id,
        recipient_phone_id=owner.phone_number_id,
    )


@pytest.mark.asyncio
class TestActiveEndpointNonTerminal:
    async def test_missed_session_returned_as_active(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner(db_session)
        session = await _session(db_session, owner, status=SessionStatus.MISSED.value)

        response = await client.get("/api/v1/sessions/active", headers=_auth(owner))
        assert response.status_code == 200
        data = response.json()
        assert data is not None
        assert data["id"] == str(session.id)
        assert data["status"] == "missed"

    async def test_alerted_session_returned_with_acknowledged_flag(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner(db_session)
        member = await _add_member(db_session, owner)
        session = await _session(db_session, owner, status=SessionStatus.ALERTED.value)
        db_session.add(
            Alert(
                session_id=session.id,
                sent_to_phone_id=member.contact_phone_number_id,
                alert_type=AlertType.MISSED_SESSION,
                status=AlertStatus.ACKNOWLEDGED,
                sent_at=datetime.now(UTC),
                acknowledged_at=datetime.now(UTC),
            )
        )
        await db_session.commit()

        response = await client.get("/api/v1/sessions/active", headers=_auth(owner))
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alerted"
        assert data["alert_acknowledged"] is True

    async def test_active_preferred_over_missed_and_no_500(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Two non-terminal sessions (an old MISSED + a new ACTIVE, e.g. SOS
        during a check-in) must not raise MultipleResultsFound — ACTIVE wins."""
        owner = await _owner(db_session)
        await _session(db_session, owner, status=SessionStatus.MISSED.value)
        active = await _session(
            db_session, owner, status=SessionStatus.ACTIVE.value, minutes_offset=60
        )

        response = await client.get("/api/v1/sessions/active", headers=_auth(owner))
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(active.id)
        assert data["status"] == "active"

    async def test_completed_session_still_excluded(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner(db_session)
        await _session(db_session, owner, status=SessionStatus.COMPLETED.value)

        response = await client.get("/api/v1/sessions/active", headers=_auth(owner))
        assert response.status_code == 200
        assert response.json() is None

    async def test_new_checkin_blocked_while_missed_session_lingers(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A lingering MISSED incident must be marked safe before starting a
        new session — otherwise the new session would shadow the live one."""
        owner = await _owner(db_session)
        db_session.add(
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
        await db_session.commit()
        await _add_member(db_session, owner)
        await _session(db_session, owner, status=SessionStatus.MISSED.value)

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(owner),
            json={
                "session_type": "checkin",
                "expected_return_time": (
                    datetime.now(UTC) + timedelta(hours=2)
                ).isoformat(),
            },
        )
        assert response.status_code == 400


@pytest.mark.asyncio
class TestCircleUnreachable:
    async def test_false_for_active_session(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner(db_session)
        session = await _session(
            db_session, owner, status=SessionStatus.ACTIVE.value, minutes_offset=60
        )

        response = await client.get(
            f"/api/v1/sessions/{session.id}", headers=_auth(owner)
        )
        assert response.json()["circle_unreachable"] is False

    async def test_true_when_all_deliveries_terminally_undeliverable(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner(db_session)
        session = await _session(db_session, owner, status=SessionStatus.MISSED.value)
        db_session.add(_delivery(session, owner, DeliveryStatus.EXHAUSTED))
        db_session.add(_delivery(session, owner, DeliveryStatus.REFUSED))
        await db_session.commit()

        for url in (f"/api/v1/sessions/{session.id}", "/api/v1/sessions/active"):
            response = await client.get(url, headers=_auth(owner))
            assert response.json()["circle_unreachable"] is True, url

    async def test_false_while_a_delivery_is_still_retrying(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner(db_session)
        session = await _session(db_session, owner, status=SessionStatus.MISSED.value)
        db_session.add(_delivery(session, owner, DeliveryStatus.EXHAUSTED))
        db_session.add(_delivery(session, owner, DeliveryStatus.PENDING))
        await db_session.commit()

        response = await client.get(
            f"/api/v1/sessions/{session.id}", headers=_auth(owner)
        )
        assert response.json()["circle_unreachable"] is False

    async def test_false_when_someone_was_reached(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner(db_session)
        session = await _session(db_session, owner, status=SessionStatus.MISSED.value)
        db_session.add(_delivery(session, owner, DeliveryStatus.SENT))
        await db_session.commit()

        response = await client.get(
            f"/api/v1/sessions/{session.id}", headers=_auth(owner)
        )
        assert response.json()["circle_unreachable"] is False

    async def test_false_in_dispatch_window_when_members_exist(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Freshly MISSED, no delivery rows yet, but the circle has members —
        the worker just hasn't enqueued yet. Must not flash 'unreachable'."""
        owner = await _owner(db_session)
        await _add_member(db_session, owner)
        session = await _session(db_session, owner, status=SessionStatus.MISSED.value)

        response = await client.get(
            f"/api/v1/sessions/{session.id}", headers=_auth(owner)
        )
        assert response.json()["circle_unreachable"] is False

    async def test_true_when_circle_emptied_before_dispatch(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """MISSED with no delivery rows and no active members: no one is
        coming and no dispatch will ever create rows — tell the owner."""
        owner = await _owner(db_session)
        session = await _session(db_session, owner, status=SessionStatus.MISSED.value)

        response = await client.get(
            f"/api/v1/sessions/{session.id}", headers=_auth(owner)
        )
        assert response.json()["circle_unreachable"] is True

    async def test_false_once_alerted(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _owner(db_session)
        session = await _session(db_session, owner, status=SessionStatus.ALERTED.value)
        db_session.add(_delivery(session, owner, DeliveryStatus.EXHAUSTED))
        await db_session.commit()

        response = await client.get(
            f"/api/v1/sessions/{session.id}", headers=_auth(owner)
        )
        assert response.json()["circle_unreachable"] is False
