"""Tests for the Twilio SMS delivery webhook.

The webhook resolves the notification_deliveries row by provider_message_id and
applies the receipt (delivered / failed), rolling the linked Alert.status up.
"""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.models.user import User
from tests.helpers import create_test_user

SID = "SM_TEST_123"


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await create_test_user(db_session, phone_number="+14155557001")


@pytest_asyncio.fixture
async def contact(db_session: AsyncSession) -> User:
    return await create_test_user(db_session, phone_number="+14155557002")


@pytest_asyncio.fixture
async def sms_delivery(
    db_session: AsyncSession, owner: User, contact: User
) -> NotificationDelivery:
    """A SENT SMS delivery (linked to an Alert) awaiting a provider receipt."""
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
        sent_to_phone_id=contact.phone_number_id,
        alert_type=AlertType.MISSED_SESSION,
        status=AlertStatus.SENT,
        message="Test alert",
    )
    db_session.add(alert)
    await db_session.flush()

    now = datetime.now(UTC)
    await crud_nd.enqueue(
        db_session,
        rows=[
            DeliveryDraft(
                dedupe_key="wh-d1",
                kind=NotificationKind.CIRCLE_ALERT,
                channel=DeliveryChannel.SMS,
                body="Test alert",
                next_attempt_at=now,
                recipient_phone_id=contact.phone_number_id,
                session_id=session.id,
                alert_id=alert.id,
            )
        ],
    )
    d = (
        await db_session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.dedupe_key == "wh-d1"
            )
        )
    ).scalar_one()
    await crud_nd.mark_sent(
        db_session, delivery=d, provider="twilio", provider_message_id=SID, now=now
    )
    await db_session.commit()
    return d


@pytest.mark.asyncio
class TestTwilioDeliveryWebhook:
    async def test_delivered_marks_delivery_and_alert_delivered(
        self, client: AsyncClient, db_session: AsyncSession, sms_delivery
    ):
        response = await client.post(
            "/webhooks/delivery/twilio",
            data={"MessageSid": SID, "MessageStatus": "delivered"},
        )
        assert response.status_code == 200
        await db_session.refresh(sms_delivery)
        assert sms_delivery.status == DeliveryStatus.DELIVERED
        alert = await db_session.get(Alert, sms_delivery.alert_id)
        assert alert.status == AlertStatus.DELIVERED

    async def test_failed_marks_delivery_failed_retryable(
        self, client: AsyncClient, db_session: AsyncSession, sms_delivery
    ):
        response = await client.post(
            "/webhooks/delivery/twilio",
            data={"MessageSid": SID, "MessageStatus": "failed"},
        )
        assert response.status_code == 200
        await db_session.refresh(sms_delivery)
        assert sms_delivery.status == DeliveryStatus.FAILED  # retryable

    async def test_undelivered_marks_delivery_failed(
        self, client: AsyncClient, db_session: AsyncSession, sms_delivery
    ):
        response = await client.post(
            "/webhooks/delivery/twilio",
            data={"MessageSid": SID, "MessageStatus": "undelivered"},
        )
        assert response.status_code == 200
        await db_session.refresh(sms_delivery)
        assert sms_delivery.status == DeliveryStatus.FAILED

    async def test_unknown_message_sid_returns_ok(self, client: AsyncClient):
        response = await client.post(
            "/webhooks/delivery/twilio",
            data={"MessageSid": "SM_UNKNOWN", "MessageStatus": "delivered"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_missing_message_sid_ignored(self, client: AsyncClient):
        response = await client.post(
            "/webhooks/delivery/twilio",
            data={"MessageStatus": "delivered"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
