"""send_due_deliveries + poll_expo_receipts: the push/SMS send paths and
receipt confirmation, with the providers monkeypatched.

Related: app/services/notification_outbox.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification_delivery import DeliveryDraft
from app.crud.notification_delivery import crud_notification_delivery as crud
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationKind,
)
from app.models.session import Session
from app.services import notification_outbox as outbox
from app.services.sms import SMSProvider, SMSResult
from tests.helpers import create_test_user

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
TOKEN = "ExponentPushToken[abc]"


async def _user(db, phone, *, token=TOKEN):
    u = await create_test_user(db, phone_number=phone)
    u.expo_push_token = token
    await db.commit()
    await db.refresh(u)
    return u


async def _session(db, user) -> Session:
    s = Session(user_id=user.id, expected_return_time=NOW, status="missed")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def _enqueue(db, *, key, kind, channel, user_id=None, phone_id=None, session_id=None):
    await crud.enqueue(
        db,
        rows=[
            DeliveryDraft(
                dedupe_key=key,
                kind=kind,
                channel=channel,
                body="hi",
                next_attempt_at=NOW,
                recipient_user_id=user_id,
                recipient_phone_id=phone_id,
                session_id=session_id,
                data={"type": "x"},
            )
        ],
    )


def _push(**ov):
    base = {"status": "success", "ok_tokens": [], "dead_tokens": [], "ticket_ids": {}}
    base.update(ov)
    return base


def _patch_push(monkeypatch, result):
    async def fake(*a, **k):
        return result

    monkeypatch.setattr(
        outbox.ExpoPushNotificationService, "send_notification", fake
    )


@pytest.mark.asyncio
class TestSendPush:
    async def test_accepted_receipt_kind_is_sent(self, db_session: AsyncSession, monkeypatch):
        # Circle-directed kinds are SMS-only (owner decision), so the push
        # mechanics here use an owner push kind (CIRCLE_ALERTED). Every push
        # kind is receipt-tracked, so an accepted push stays SENT.
        u = await _user(db_session, "+14155592001")
        s = await _session(db_session, u)
        await _enqueue(db_session, key="p1", kind=NotificationKind.CIRCLE_ALERTED, channel=DeliveryChannel.PUSH, user_id=u.id, session_id=s.id)
        _patch_push(monkeypatch, _push(ok_tokens=[TOKEN], ticket_ids={TOKEN: "t1"}))

        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert counts["sent"] == 1
        # receipt-tracked kind stays SENT (awaiting a receipt), so not re-due
        assert await crud.get_due(db_session, now=NOW) == []
        d = await crud.get_by_provider_message_id(db_session, "t1")
        assert d is not None and d.status == DeliveryStatus.SENT

    async def test_ticket_error_backs_off(self, db_session: AsyncSession, monkeypatch):
        u = await _user(db_session, "+14155592003")
        s = await _session(db_session, u)
        await _enqueue(db_session, key="p3", kind=NotificationKind.CIRCLE_ALERTED, channel=DeliveryChannel.PUSH, user_id=u.id, session_id=s.id)
        _patch_push(monkeypatch, _push(ok_tokens=[]))

        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert counts["failed"] == 1

    async def test_dead_token_refused_and_cleared(self, db_session: AsyncSession, monkeypatch):
        u = await _user(db_session, "+14155592004")
        s = await _session(db_session, u)
        await _enqueue(db_session, key="p4", kind=NotificationKind.CIRCLE_ALERTED, channel=DeliveryChannel.PUSH, user_id=u.id, session_id=s.id)
        _patch_push(monkeypatch, _push(ok_tokens=[], dead_tokens=[TOKEN]))

        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert counts["refused"] == 1
        await db_session.refresh(u)
        assert u.expo_push_token is None  # dead token cleared

    async def test_no_token_refused(self, db_session: AsyncSession, monkeypatch):
        u = await _user(db_session, "+14155592005", token=None)
        s = await _session(db_session, u)
        await _enqueue(db_session, key="p5", kind=NotificationKind.CIRCLE_ALERTED, channel=DeliveryChannel.PUSH, user_id=u.id, session_id=s.id)
        _patch_push(monkeypatch, _push())

        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert counts["refused"] == 1


@pytest.mark.asyncio
class TestSendSms:
    async def test_success_is_sent(self, db_session: AsyncSession, monkeypatch):
        u = await _user(db_session, "+14155592010")
        s = await _session(db_session, u)
        await _enqueue(db_session, key="s1", kind=NotificationKind.CIRCLE_ALERT, channel=DeliveryChannel.SMS, phone_id=u.phone_number_id, session_id=s.id)

        async def fake(db, phone, body, **k):
            return SMSResult(success=True, message_id="sid", provider=SMSProvider.TWILIO)

        monkeypatch.setattr(outbox.sms_opt_out, "gated_send_sms", fake)
        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert counts["sent"] == 1

    async def test_opted_out_is_refused(self, db_session: AsyncSession, monkeypatch):
        u = await _user(db_session, "+14155592011")
        s = await _session(db_session, u)
        await _enqueue(db_session, key="s2", kind=NotificationKind.CIRCLE_ALERT, channel=DeliveryChannel.SMS, phone_id=u.phone_number_id, session_id=s.id)

        async def fake(db, phone, body, **k):
            return SMSResult(success=False, error="opted_out")

        monkeypatch.setattr(outbox.sms_opt_out, "gated_send_sms", fake)
        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert counts["refused"] == 1

    async def test_failure_backs_off(self, db_session: AsyncSession, monkeypatch):
        u = await _user(db_session, "+14155592012")
        s = await _session(db_session, u)
        await _enqueue(db_session, key="s3", kind=NotificationKind.CIRCLE_ALERT, channel=DeliveryChannel.SMS, phone_id=u.phone_number_id, session_id=s.id)

        async def fake(db, phone, body, **k):
            return SMSResult(success=False, error="provider down")

        monkeypatch.setattr(outbox.sms_opt_out, "gated_send_sms", fake)
        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert counts["failed"] == 1


@pytest.mark.asyncio
class TestReceipts:
    async def test_ok_receipt_delivers(self, db_session: AsyncSession, monkeypatch):
        u = await _user(db_session, "+14155592020")
        s = await _session(db_session, u)
        await _enqueue(db_session, key="r1", kind=NotificationKind.CIRCLE_ALERTED, channel=DeliveryChannel.PUSH, user_id=u.id, session_id=s.id)
        _patch_push(monkeypatch, _push(ok_tokens=[TOKEN], ticket_ids={TOKEN: "tk"}))
        await outbox.send_due_deliveries(db_session, now=NOW)  # sent_at = NOW

        async def fake_receipts(ids):
            return {"status": "success", "receipts": {"tk": {"ok": True, "dead": False, "error": None}}}

        monkeypatch.setattr(
            outbox.ExpoPushNotificationService, "get_receipts", fake_receipts
        )
        # Poll a minute later so the row is past the 30s receipt-age gate.
        counts = await outbox.poll_expo_receipts(
            db_session, now=NOW + timedelta(minutes=1)
        )
        assert counts["delivered"] == 1
