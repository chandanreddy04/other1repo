"""The emptied-Circle cascade treats a MISSED/ALERTED session as mid-session.

`sms_opt_out.compute_owner_impacts` (shared by the STOP cascade and the web
leave path) decides "is the owner in a session" with the non-terminal set
(ACTIVE, MISSED, ALERTED — `crud.session.NON_TERMINAL_STATUSES`, the same set
`crud_session.get_active_session` uses). An owner whose session has already
gone MISSED/ALERTED is mid-incident, so losing their last member must send
the push+SMS CIRCLE_EMPTIED_MID_SESSION (O10), not the push-only
CIRCLE_EMPTIED (O9). A COMPLETED session is history → O9.

Related: app/services/sms_opt_out.py (compute_owner_impacts),
app/services/notification_helpers.py (_cascade_kind),
app/api/v1/endpoints/inbound_sms.py (_handle_stop),
app/services/circle_invitations.py (leave_circle), docs/notifications.md O9/O10.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.circle_of_trust import crud_circle_of_trust
from app.crud.phone_number import crud_phone_number
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.schemas.circle_of_trust import CircleOfTrustMemberCreate
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio

# Dispatch runs in the reconciler — patch it there so no provider is touched.
_NO_PROVIDERS = (
    patch(
        "app.services.notification_outbox.ExpoPushNotificationService.send_notification",
        new_callable=AsyncMock,
        return_value={"ok_tokens": [], "dead_tokens": [], "ticket_ids": {}},
    ),
    patch(
        "app.services.notification_outbox.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
        return_value=None,
    ),
)


async def _session(db: AsyncSession, owner: User, status: SessionStatus) -> Session:
    s = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=status.value,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _only_phone_member(
    db: AsyncSession, owner: User, contact_phone: str
) -> CircleOfTrustMember:
    phone, _ = await crud_phone_number.get_or_create(db, number=contact_phone)
    m = CircleOfTrustMember(
        user_id=owner.id,
        nickname="Bob",
        contact_phone_number_id=phone.id,
        status=ContactStatus.ACTIVE,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def _kind_rows(
    db: AsyncSession, owner: User, kind: NotificationKind
) -> list[NotificationDelivery]:
    # Push rows carry recipient_user_id; the SMS backup row is keyed by phone
    # id — match either the owner or the owner's phone.
    return list(
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.kind == kind,
                    (NotificationDelivery.recipient_user_id == owner.id)
                    | (NotificationDelivery.recipient_phone_id == owner.phone_number_id),
                )
            )
        )
        .scalars()
        .all()
    )


async def _stop(client: AsyncClient, from_phone: str) -> None:
    with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
        resp = await client.post(
            "/webhooks/sms/twilio-inbound",
            data={"From": from_phone, "Body": "STOP"},
        )
    assert resp.status_code == 200


def _assert_mid_session(rows: list[NotificationDelivery], session: Session) -> None:
    assert {r.channel for r in rows} == {DeliveryChannel.PUSH, DeliveryChannel.SMS}
    assert all(r.session_id == session.id for r in rows)


@pytest.mark.parametrize("status", [SessionStatus.MISSED, SessionStatus.ALERTED])
async def test_stop_as_last_member_during_incident_sends_mid_session_push_and_sms(
    db_session: AsyncSession, client: AsyncClient, status: SessionStatus
) -> None:
    suffix = "1" if status == SessionStatus.MISSED else "2"
    owner = await create_test_user(db_session, phone_number=f"+1312555710{suffix}")
    session = await _session(db_session, owner, status)
    await _only_phone_member(db_session, owner, f"+1312555711{suffix}")

    await _stop(client, f"+1312555711{suffix}")

    rows = await _kind_rows(
        db_session, owner, NotificationKind.CIRCLE_EMPTIED_MID_SESSION
    )
    _assert_mid_session(rows, session)
    assert not await _kind_rows(db_session, owner, NotificationKind.CIRCLE_EMPTIED)


async def test_web_leave_as_last_member_during_missed_sends_mid_session_push_and_sms(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    owner = await create_test_user(
        db_session,
        phone_number="+13125557120",
        full_name="Ivy Inviter",
        circle_invite_code="MIDINC001",
    )
    member_user = await create_test_user(
        db_session, phone_number="+13125557121", full_name="Cody Contact"
    )
    row = await crud_circle_of_trust.create_by_phone(
        db_session,
        user_id=owner.id,
        obj_in=CircleOfTrustMemberCreate(
            contact_phone_number=member_user.phone_number, nickname="Bob"
        ),
    )
    await crud_circle_of_trust.accept_invitation(db_session, contact=row)
    session = await _session(db_session, owner, SessionStatus.MISSED)

    with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
        resp = await client.post(
            "/circles/MIDINC001/leave",
            cookies={"access_token": create_access_token(str(member_user.id))},
            follow_redirects=False,
        )
    assert resp.status_code == 303

    rows = await _kind_rows(
        db_session, owner, NotificationKind.CIRCLE_EMPTIED_MID_SESSION
    )
    _assert_mid_session(rows, session)
    assert not await _kind_rows(db_session, owner, NotificationKind.CIRCLE_EMPTIED)


async def test_stop_as_last_member_after_completed_session_sends_push_only_o9(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    owner = await create_test_user(db_session, phone_number="+13125557130")
    await _session(db_session, owner, SessionStatus.COMPLETED)
    await _only_phone_member(db_session, owner, "+13125557131")

    await _stop(client, "+13125557131")

    rows = await _kind_rows(db_session, owner, NotificationKind.CIRCLE_EMPTIED)
    assert rows and {r.channel for r in rows} == {DeliveryChannel.PUSH}
    assert not await _kind_rows(
        db_session, owner, NotificationKind.CIRCLE_EMPTIED_MID_SESSION
    )
