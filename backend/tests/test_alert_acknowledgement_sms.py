"""Acknowledgement broadcast is SMS-ONLY (owner decision 2026-07-18): the
owner gets a named SMS ("{claimer} acknowledged your alert"), every other
ACTIVE circle member — app or no app — gets the anonymous one ("{owner}'s
alert was acknowledged"), the acknowledger is excluded both ways (account
and phone), and NO pushes are created. Copy never reveals the
acknowledger's identity to the circle and never claims anyone is
"on their way".

Related: app/services/alert_acknowledgement.py, app/services/notification_policy.py,
app/services/notification_constants.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.services.alert_acknowledgement import acknowledge_alert
from tests.helpers import create_test_user

_PHONE = iter(f"+141555940{n:02d}" for n in range(1, 99))


async def _setup(
    db: AsyncSession, *, member_count: int = 2, phone_only_first: bool = False
) -> tuple[User, list[User | None], list[CircleOfTrustMember], Session]:
    """Owner + N active members + a MISSED session. contact_user is derived
    from the phone, so a phone-only member is a phone with no User."""
    owner = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Olive Owner"
    )
    contacts: list[User | None] = []
    members: list[CircleOfTrustMember] = []
    for i in range(member_count):
        number = next(_PHONE)
        if i == 0 and phone_only_first:
            phone, _ = await crud_phone_number.get_or_create(db, number=number)
            phone_id = phone.id
            contacts.append(None)
        else:
            contact = await create_test_user(
                db, phone_number=number, full_name=f"Contact {i}"
            )
            phone_id = contact.phone_number_id
            contacts.append(contact)
        member = CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=phone_id,
            nickname=f"Contact {i}",
            status=ContactStatus.ACTIVE.value,
        )
        db.add(member)
        members.append(member)
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=SessionStatus.MISSED.value,
    )
    db.add(session)
    await db.commit()
    for m in members:
        await db.refresh(m)
    await db.refresh(session)
    return owner, contacts, members, session


async def _alert_for(
    db: AsyncSession,
    session: Session,
    *,
    user_id=None,
    phone_id=None,
) -> Alert:
    alert = Alert(
        session_id=session.id,
        sent_to_user_id=user_id,
        sent_to_phone_id=phone_id,
        alert_type=AlertType.MISSED_SESSION,
        status=AlertStatus.SENT,
        sent_at=datetime.now(UTC),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


async def _claim_rows(
    db: AsyncSession, session_id
) -> list[NotificationDelivery]:
    return (
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.session_id == session_id,
                    NotificationDelivery.kind == NotificationKind.ALERT_ACKNOWLEDGED,
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
class TestAcknowledgementSMSBroadcast:
    async def test_sms_only_to_owner_and_other_members(
        self, db_session: AsyncSession
    ):
        owner, contacts, members, session = await _setup(db_session)
        alert = await _alert_for(db_session, session, user_id=contacts[0].id)

        await acknowledge_alert(db_session, alert=alert)

        rows = await _claim_rows(db_session, session.id)
        # Every row is SMS — never a push.
        assert rows and all(r.channel == DeliveryChannel.SMS for r in rows)
        recipients = {r.recipient_phone_id for r in rows}
        # Owner + the OTHER member; the acknowledger is excluded.
        assert recipients == {
            owner.phone_number_id,
            members[1].contact_phone_number_id,
        }

    async def test_owner_sms_is_named_member_sms_is_anonymous(
        self, db_session: AsyncSession
    ):
        owner, contacts, members, session = await _setup(db_session)
        alert = await _alert_for(db_session, session, user_id=contacts[0].id)

        await acknowledge_alert(db_session, alert=alert)

        rows = await _claim_rows(db_session, session.id)
        by_phone = {r.recipient_phone_id: r.body for r in rows}
        owner_sms = by_phone[owner.phone_number_id]
        member_sms = by_phone[members[1].contact_phone_number_id]
        # Owner learns WHO acknowledged — their own contact.
        assert "Contact 0" in owner_sms
        assert "acknowledged your alert" in owner_sms
        # The circle never learns the acknowledger's identity, and copy
        # never claims anyone is "on their way".
        assert "Contact 0" not in member_sms
        assert member_sms == "Made It Home: Olive's alert was acknowledged."
        for body in by_phone.values():
            assert "on it" not in body
            assert "checking on" not in body

    async def test_phone_only_acknowledger_never_texts_themselves(
        self, db_session: AsyncSession
    ):
        """A public-page claim by an SMS-only contact (no account) must be
        excluded by phone id — otherwise they'd get their own broadcast."""
        owner, _contacts, members, session = await _setup(
            db_session, phone_only_first=True
        )
        alert = await _alert_for(
            db_session, session, phone_id=members[0].contact_phone_number_id
        )

        await acknowledge_alert(db_session, alert=alert)

        rows = await _claim_rows(db_session, session.id)
        recipients = {r.recipient_phone_id for r in rows}
        assert members[0].contact_phone_number_id not in recipients
        assert recipients == {
            owner.phone_number_id,
            members[1].contact_phone_number_id,
        }

    async def test_reacknowledging_broadcasts_nothing_new(
        self, db_session: AsyncSession
    ):
        _owner, contacts, _members, session = await _setup(db_session)
        alert = await _alert_for(db_session, session, user_id=contacts[0].id)

        await acknowledge_alert(db_session, alert=alert)
        first = len(await _claim_rows(db_session, session.id))
        await acknowledge_alert(db_session, alert=alert)
        assert len(await _claim_rows(db_session, session.id)) == first

    async def test_second_acknowledger_sends_a_fresh_batch(
        self, db_session: AsyncSession
    ):
        _owner, contacts, _members, session = await _setup(
            db_session, member_count=3
        )
        alert_a = await _alert_for(db_session, session, user_id=contacts[0].id)
        alert_b = await _alert_for(db_session, session, user_id=contacts[1].id)

        await acknowledge_alert(db_session, alert=alert_a)
        count_after_a = len(await _claim_rows(db_session, session.id))
        await acknowledge_alert(db_session, alert=alert_b)
        assert len(await _claim_rows(db_session, session.id)) > count_after_a
