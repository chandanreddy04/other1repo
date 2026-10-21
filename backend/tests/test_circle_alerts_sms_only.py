"""Circle members are notified by SMS only (owner decision).

No push notifications go to Circle members (the trusted contacts alerted
about a session owner) for circle alerts, re-nudges, or all-clear —
regardless of whether the member has an app account. Owner-directed pushes
(e.g. the owner's `circle_alerted` push on the MISSED→ALERTED promotion) are
unchanged, and every push kind is receipt-tracked so each push is auditable.

Related: app/services/notification_policy.py (CIRCLE_ALERT, CIRCLE_RENUDGE,
ALL_CLEAR, ALERT_ACKNOWLEDGED channels; track_expo_receipts),
app/services/session_tasks.py (_enqueue_circle_alerts),
app/services/notification_outbox.py (_enqueue_renudge),
app/services/notification_helpers.py (send_all_clear_to_circle).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification_delivery import DeliveryDraft
from app.crud.notification_delivery import crud_notification_delivery as crud
from app.crud.phone_number import crud_phone_number
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.services import notification_outbox as outbox
from app.services.notification_policy import POLICIES
from app.services.session_tasks import complete_session_with_all_clear, process_overdue
from tests.helpers import create_test_user

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
MEMBER_TOKEN = "ExponentPushToken[amy]"

SMS_ONLY_CIRCLE_KINDS = (
    NotificationKind.CIRCLE_ALERT,
    NotificationKind.CIRCLE_RENUDGE,
    NotificationKind.ALL_CLEAR,
    NotificationKind.ALERT_ACKNOWLEDGED,
)


class TestPolicyInvariants:
    def test_circle_member_kinds_are_sms_only(self):
        for kind in SMS_ONLY_CIRCLE_KINDS:
            assert POLICIES[kind].channels == (DeliveryChannel.SMS,), kind

    def test_every_push_kind_tracks_receipts_and_only_push_kinds_do(self):
        # Every push we send is auditable via poll_expo_receipts; the
        # reconciler has no "accepted = delivered" path for a push.
        for kind, policy in POLICIES.items():
            has_push = DeliveryChannel.PUSH in policy.channels
            assert policy.track_expo_receipts == has_push, kind


async def _owner(db: AsyncSession, phone: str) -> User:
    return await create_test_user(
        db,
        phone_number=phone,
        full_name="Ona Owner",
        expo_push_token="ExponentPushToken[owner]",
    )


async def _app_member(db: AsyncSession, owner: User, phone: str) -> User:
    """A circle member who has an app account (and a push token)."""
    contact = await create_test_user(
        db,
        phone_number=phone,
        full_name="Amy AppMember",
        expo_push_token=MEMBER_TOKEN,
    )
    db.add(
        CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=contact.phone_number_id,
            nickname=contact.full_name,
            status=ContactStatus.ACTIVE.value,
        )
    )
    await db.commit()
    return contact


async def _no_app_member(db: AsyncSession, owner: User, phone: str) -> UUID:
    """A circle member with no app account — phone-only. Returns the phone id."""
    phone_row, _ = await crud_phone_number.get_or_create(db, number=phone)
    db.add(
        CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=phone_row.id,
            nickname="Nina NoApp",
            status=ContactStatus.ACTIVE.value,
        )
    )
    await db.commit()
    return phone_row.id


async def _deliveries(
    db: AsyncSession, session_id, kind: NotificationKind
) -> list[NotificationDelivery]:
    return list(
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.session_id == session_id,
                    NotificationDelivery.kind == kind,
                )
            )
        )
        .scalars()
        .all()
    )


def _ok_sms():
    return AsyncMock(
        return_value=MagicMock(success=True, message_id="SM1", provider=None)
    )


def _assert_no_push_to_member(mock_push_cls) -> None:
    for call in mock_push_cls.send_notification.call_args_list:
        assert MEMBER_TOKEN not in call.kwargs.get("push_tokens", [])


def _assert_sms_only_to_both(rows, app_contact: User, no_app_phone_id: UUID):
    assert {r.channel for r in rows} == {DeliveryChannel.SMS}
    assert all(r.recipient_user_id is None for r in rows)
    # One SMS per member: the app-account member AND the phone-only member.
    assert sorted(str(r.recipient_phone_id) for r in rows) == sorted(
        [str(app_contact.phone_number_id), str(no_app_phone_id)]
    )


@pytest.mark.asyncio
class TestSosAndMissedCircleAlertsSMSOnly:
    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_sos_session_alerts_circle_by_sms_only(
        self, mock_push_cls, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = _ok_sms()
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await _owner(db_session, "+14155597001")
        app_contact = await _app_member(db_session, owner, "+14155597002")
        no_app_phone_id = await _no_app_member(db_session, owner, "+14155597003")

        session = Session(
            user_id=owner.id,
            session_type=SessionType.SOS.value,
            expected_return_time=NOW,
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        result = await process_overdue(db_session, str(session.id))
        assert result["alerts_sent"] is True

        rows = await _deliveries(
            db_session, session.id, NotificationKind.CIRCLE_ALERT
        )
        _assert_sms_only_to_both(rows, app_contact, no_app_phone_id)
        _assert_no_push_to_member(mock_push_cls)

        # Owner-directed push is unaffected: circle_alerted still fires on
        # the MISSED→ALERTED promotion.
        owner_rows = await _deliveries(
            db_session, session.id, NotificationKind.CIRCLE_ALERTED
        )
        assert len(owner_rows) == 1
        assert owner_rows[0].channel == DeliveryChannel.PUSH
        assert owner_rows[0].recipient_user_id == owner.id

    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_missed_checkin_alerts_circle_by_sms_only(
        self, mock_push_cls, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = _ok_sms()
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await _owner(db_session, "+14155597004")
        app_contact = await _app_member(db_session, owner, "+14155597005")
        no_app_phone_id = await _no_app_member(db_session, owner, "+14155597006")

        session = Session(
            user_id=owner.id,
            session_type=SessionType.CHECKIN.value,
            expected_return_time=NOW - timedelta(minutes=10),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        result = await process_overdue(db_session, str(session.id))
        assert result["alerts_sent"] is True

        rows = await _deliveries(
            db_session, session.id, NotificationKind.CIRCLE_ALERT
        )
        _assert_sms_only_to_both(rows, app_contact, no_app_phone_id)
        _assert_no_push_to_member(mock_push_cls)


@pytest.mark.asyncio
class TestReNudgeSMSOnly:
    async def test_renudge_is_sms_only_for_every_member(
        self, db_session: AsyncSession
    ):
        owner = await _owner(db_session, "+14155597007")
        app_contact = await _app_member(db_session, owner, "+14155597008")
        no_app_phone_id = await _no_app_member(db_session, owner, "+14155597009")

        session = Session(
            user_id=owner.id,
            session_type=SessionType.CHECKIN.value,
            expected_return_time=NOW - timedelta(minutes=5),
            status=SessionStatus.MISSED.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        # A reached alert to the app-account member so the promotion fires.
        alert = Alert(
            session_id=session.id,
            sent_to_user_id=app_contact.id,
            alert_type=AlertType.MISSED_SESSION,
            status=AlertStatus.SENT,
            message="hi",
            sent_at=NOW,
        )
        db_session.add(alert)
        await db_session.flush()
        await crud.enqueue(
            db_session,
            rows=[
                DeliveryDraft(
                    dedupe_key="ca-reached",
                    kind=NotificationKind.CIRCLE_ALERT,
                    channel=DeliveryChannel.SMS,
                    body="hi",
                    next_attempt_at=NOW,
                    recipient_phone_id=app_contact.phone_number_id,
                    session_id=session.id,
                    alert_id=alert.id,
                )
            ],
        )
        [d] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=d, provider="twilio", provider_message_id="tk1", now=NOW
        )
        await db_session.commit()

        result = await outbox.derive_session_promotions(db_session, now=NOW)
        assert result["promoted"] == 1

        renudge_rows = await _deliveries(
            db_session, session.id, NotificationKind.CIRCLE_RENUDGE
        )
        _assert_sms_only_to_both(renudge_rows, app_contact, no_app_phone_id)


@pytest.mark.asyncio
class TestAllClearSMSOnly:
    @patch("app.services.notification_outbox.sms_opt_out")
    @patch("app.services.notification_outbox.ExpoPushNotificationService")
    async def test_all_clear_is_sms_only_for_every_member(
        self, mock_push_cls, mock_sms, db_session: AsyncSession
    ):
        mock_sms.gated_send_sms = _ok_sms()
        mock_push_cls.send_notification = AsyncMock(return_value={})

        owner = await _owner(db_session, "+14155597010")
        app_contact = await _app_member(db_session, owner, "+14155597011")
        no_app_phone_id = await _no_app_member(db_session, owner, "+14155597012")

        session = Session(
            user_id=owner.id,
            session_type=SessionType.CHECKIN.value,
            expected_return_time=NOW - timedelta(minutes=10),
            status=SessionStatus.MISSED.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        await complete_session_with_all_clear(db_session, session, owner)

        rows = await _deliveries(db_session, session.id, NotificationKind.ALL_CLEAR)
        _assert_sms_only_to_both(rows, app_contact, no_app_phone_id)
        _assert_no_push_to_member(mock_push_cls)
