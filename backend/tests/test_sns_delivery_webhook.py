"""Tests for the SNS delivery webhook endpoint.

The endpoint is the receiving half of an SNS → CloudWatch Logs → Lambda
bridge. The Lambda is provisioned in PR 12; this test suite covers the
backend contract independently: HMAC verification, payload parsing, and
alert status updates.
"""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.notification_delivery import DeliveryDraft
from app.crud.notification_delivery import crud_notification_delivery as crud_nd
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus, SessionType
from tests.helpers import create_test_user

SECRET = "super-secret-shared-with-lambda"


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest_asyncio.fixture
async def sns_delivery(db_session: AsyncSession) -> NotificationDelivery:
    """A SENT SMS delivery (SNS provider) with a known provider_message_id,
    ready for the webhook to mark delivered/failed."""
    owner = await create_test_user(db_session, phone_number="+14155557001")
    recipient = await create_test_user(db_session, phone_number="+14155557002")
    session = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=5),
        status=SessionStatus.ALERTED.value,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    alert = Alert(
        session_id=session.id,
        sent_to_phone_id=recipient.phone_number_id,
        alert_type=AlertType.MISSED_SESSION,
        status=AlertStatus.SENT,
        message="Test alert",
    )
    db_session.add(alert)
    await db_session.flush()

    now = datetime.now(UTC)
    mid = f"sns-{uuid4().hex[:12]}"
    await crud_nd.enqueue(
        db_session,
        rows=[
            DeliveryDraft(
                dedupe_key=f"sns-wh-{mid}",
                kind=NotificationKind.CIRCLE_ALERT,
                channel=DeliveryChannel.SMS,
                body="Test alert",
                next_attempt_at=now,
                recipient_phone_id=recipient.phone_number_id,
                session_id=session.id,
                alert_id=alert.id,
            )
        ],
    )
    d = (
        await db_session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.dedupe_key == f"sns-wh-{mid}"
            )
        )
    ).scalar_one()
    await crud_nd.mark_sent(
        db_session, delivery=d, provider="sns", provider_message_id=mid, now=now
    )
    await db_session.commit()
    return d


@pytest.mark.asyncio
class TestSNSWebhookAuth:
    async def test_rejects_when_secret_unset(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        """Closed-by-default: if the env hasn't opted in (no secret set), any
        signature is rejected — better than silently accepting unverified events."""
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", "")
        body = json.dumps({"notification": {"messageId": "x"}, "status": "SUCCESS"}).encode()
        resp = await client.post(
            "/webhooks/delivery/sns",
            content=body,
            headers={"X-MIH-Signature": _sign(body, "any")},
        )
        assert resp.status_code == 403

    async def test_rejects_missing_signature_header(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", SECRET)
        body = json.dumps({"notification": {"messageId": "x"}, "status": "SUCCESS"}).encode()
        resp = await client.post("/webhooks/delivery/sns", content=body)
        assert resp.status_code == 403

    async def test_rejects_wrong_signature(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", SECRET)
        body = json.dumps({"notification": {"messageId": "x"}, "status": "SUCCESS"}).encode()
        resp = await client.post(
            "/webhooks/delivery/sns",
            content=body,
            headers={"X-MIH-Signature": _sign(body, "wrong-secret")},
        )
        assert resp.status_code == 403

    async def test_accepts_correct_signature(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", SECRET)
        body = json.dumps([]).encode()
        resp = await client.post(
            "/webhooks/delivery/sns",
            content=body,
            headers={"X-MIH-Signature": _sign(body)},
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
class TestSNSWebhookPayload:
    async def test_rejects_invalid_json(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", SECRET)
        body = b"not json"
        resp = await client.post(
            "/webhooks/delivery/sns",
            content=body,
            headers={"X-MIH-Signature": _sign(body)},
        )
        assert resp.status_code == 400

    async def test_success_marks_alert_delivered(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        sns_delivery: NotificationDelivery,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", SECRET)
        payload = {
            "notification": {"messageId": sns_delivery.provider_message_id},
            "status": "SUCCESS",
        }
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/webhooks/delivery/sns",
            content=body,
            headers={"X-MIH-Signature": _sign(body)},
        )
        assert resp.status_code == 200

        await db_session.refresh(sns_delivery)
        assert sns_delivery.status == DeliveryStatus.DELIVERED

    async def test_failure_marks_alert_failed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        sns_delivery: NotificationDelivery,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", SECRET)
        payload = {
            "notification": {"messageId": sns_delivery.provider_message_id},
            "status": "FAILURE",
        }
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/webhooks/delivery/sns",
            content=body,
            headers={"X-MIH-Signature": _sign(body)},
        )
        assert resp.status_code == 200

        await db_session.refresh(sns_delivery)
        assert sns_delivery.status == DeliveryStatus.FAILED

    async def test_unknown_message_id_is_silent(
        self,
        client: AsyncClient,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Lambda batches may include events for messages we don't recognize
        (e.g., retried records). Should 200 without raising."""
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", SECRET)
        payload = {"notification": {"messageId": "never-seen"}, "status": "SUCCESS"}
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/webhooks/delivery/sns",
            content=body,
            headers={"X-MIH-Signature": _sign(body)},
        )
        assert resp.status_code == 200

    async def test_batch_payload_processes_all_records(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        sns_delivery: NotificationDelivery,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Lambda may forward multiple delivery records per invocation."""
        monkeypatch.setattr(settings, "AWS_SNS_DELIVERY_WEBHOOK_SECRET", SECRET)
        payload = [
            {"notification": {"messageId": "unknown-1"}, "status": "SUCCESS"},
            {
                "notification": {"messageId": sns_delivery.provider_message_id},
                "status": "SUCCESS",
            },
            {"notification": {"messageId": "unknown-2"}, "status": "FAILURE"},
        ]
        body = json.dumps(payload).encode()

        resp = await client.post(
            "/webhooks/delivery/sns",
            content=body,
            headers={"X-MIH-Signature": _sign(body)},
        )
        assert resp.status_code == 200

        await db_session.refresh(sns_delivery)
        assert sns_delivery.status == DeliveryStatus.DELIVERED
