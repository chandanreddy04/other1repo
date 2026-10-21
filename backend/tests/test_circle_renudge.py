"""Circle re-nudge (defect 4 — the never-built escalation).

When a session is promoted MISSED → ALERTED, a circle re-nudge is enqueued for
every active circle member, fired ALERT_REMINDER_DELAY_MINUTES later. It is
SUPERSEDED the moment a member claims ("I'm on it") or the owner marks safe —
so it only ever reaches a circle that went silent.

Related: app/services/notification_outbox.py (_enqueue_renudge,
derive_session_promotions), app/services/alert_acknowledgement.py (supersede on acknowledgement).
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.notification_delivery import DeliveryDraft
from app.crud.notification_delivery import crud_notification_delivery as crud
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.services import notification_outbox as outbox
from app.services.alert_acknowledgement import acknowledge_alert
from tests.helpers import create_test_user

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await create_test_user(
        db_session, phone_number="+14155595001", full_name="Ada Owner"
    )


@pytest_asyncio.fixture
async def contact(db_session: AsyncSession) -> User:
    return await create_test_user(
        db_session,
        phone_number="+14155595002",
        full_name="Bea Contact",
        expo_push_token="ExponentPushToken[bea]",
    )


async def _missed_session(db: AsyncSession, owner: User) -> Session:
    s = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=NOW - timedelta(minutes=5),
        status=SessionStatus.MISSED.value,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _add_member(db: AsyncSession, owner: User, contact: User) -> None:
    db.add(
        CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=contact.phone_number_id,
            nickname=contact.full_name,
            status=ContactStatus.ACTIVE.value,
        )
    )
    await db.commit()


async def _reached_alert(db: AsyncSession, session: Session, contact: User) -> Alert:
    """An Alert to the member plus a SENT circle_alert SMS (circle members
    are SMS-only — owner decision), so derive_session_promotions sees the
    session as reached and promotes it."""
    alert = Alert(
        session_id=session.id,
        sent_to_user_id=contact.id,
        alert_type=AlertType.MISSED_SESSION,
        status=AlertStatus.SENT,
        message="hi",
        sent_at=NOW,
    )
    db.add(alert)
    await db.flush()
    await crud.enqueue(
        db,
        rows=[
            DeliveryDraft(
                dedupe_key="ca-reached",
                kind=NotificationKind.CIRCLE_ALERT,
                channel=DeliveryChannel.SMS,
                body="hi",
                next_attempt_at=NOW,
                recipient_phone_id=contact.phone_number_id,
                session_id=session.id,
                alert_id=alert.id,
            )
        ],
    )
    [d] = await crud.get_due(db, now=NOW)
    await crud.mark_sent(
        db, delivery=d, provider="twilio", provider_message_id="SMtk1", now=NOW
    )
    await db.commit()
    return alert


async def _renudges(db: AsyncSession, session_id) -> list[NotificationDelivery]:
    return list(
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.session_id == session_id,
                    NotificationDelivery.kind == NotificationKind.CIRCLE_RENUDGE,
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
class TestReNudgeEnqueue:
    async def test_promotion_enqueues_sms_fired_after_delay(
        self, db_session: AsyncSession, owner: User, contact: User
    ):
        session = await _missed_session(db_session, owner)
        await _add_member(db_session, owner, contact)
        await _reached_alert(db_session, session, contact)

        result = await outbox.derive_session_promotions(db_session, now=NOW)
        assert result["promoted"] == 1

        rows = await _renudges(db_session, session.id)
        # Circle members are SMS-only (owner decision) — no push, even for
        # an app-account member.
        channels = {r.channel for r in rows}
        assert channels == {DeliveryChannel.SMS}

        expected_fire = NOW + timedelta(
            minutes=settings.ALERT_REMINDER_DELAY_MINUTES
        )
        for r in rows:
            assert r.next_attempt_at == expected_fire
            assert r.status == DeliveryStatus.PENDING

    async def test_no_members_no_renudge(
        self, db_session: AsyncSession, owner: User, contact: User
    ):
        # A reached alert with no *active* circle member (contact never added).
        session = await _missed_session(db_session, owner)
        await _reached_alert(db_session, session, contact)

        await outbox.derive_session_promotions(db_session, now=NOW)
        assert await _renudges(db_session, session.id) == []


@pytest.mark.asyncio
class TestReNudgeSupersede:
    async def test_claim_supersedes_pending_renudge(
        self, db_session: AsyncSession, owner: User, contact: User
    ):
        session = await _missed_session(db_session, owner)
        await _add_member(db_session, owner, contact)
        alert = await _reached_alert(db_session, session, contact)
        await outbox.derive_session_promotions(db_session, now=NOW)
        assert await _renudges(db_session, session.id)  # enqueued

        await acknowledge_alert(db_session, alert=alert)

        rows = await _renudges(db_session, session.id)
        assert rows
        assert all(r.status == DeliveryStatus.SUPERSEDED for r in rows)

    async def test_supersede_leaves_delivered_renudge_alone(
        self, db_session: AsyncSession, owner: User, contact: User
    ):
        """A re-nudge that already reached the recipient (DELIVERED — terminal)
        is not rewound by a later claim — supersede only touches non-terminal
        rows, so a delivered re-nudge stays a truthful record."""
        session = await _missed_session(db_session, owner)
        await _add_member(db_session, owner, contact)
        alert = await _reached_alert(db_session, session, contact)
        await outbox.derive_session_promotions(db_session, now=NOW)

        rows = await _renudges(db_session, session.id)
        fire_at = rows[0].next_attempt_at
        # Simulate the re-nudge firing and confirming before the claim.
        for r in rows:
            await crud.mark_sent(
                db_session,
                delivery=r,
                provider="twilio",
                provider_message_id=f"rn-{r.id}",
                now=fire_at,
            )
            await crud.mark_delivered(db_session, delivery=r, now=fire_at)
        await db_session.commit()

        await acknowledge_alert(db_session, alert=alert)

        rows = await _renudges(db_session, session.id)
        assert all(r.status == DeliveryStatus.DELIVERED for r in rows)
