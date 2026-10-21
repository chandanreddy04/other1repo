"""Tests for the Expo dead-token detection + auto-clearing.

When Expo returns `DeviceNotRegistered` for a token, the User row
holding that token gets `expo_push_token` nulled — otherwise every
future push to that user re-tries the same dead token, burning
quota and log noise.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import DeliveryStatus, NotificationDelivery
from app.services.expo_notifications import (
    ExpoPushNotificationService,
    _extract_dead_tokens,
    clear_dead_push_tokens,
)
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def test_extract_dead_tokens_picks_only_device_not_registered() -> None:
    tokens = ["ExponentPushToken[A]", "ExponentPushToken[B]", "ExponentPushToken[C]"]
    response = {
        "data": [
            {"status": "ok", "id": "..."},
            {
                "status": "error",
                "message": "...",
                "details": {"error": "DeviceNotRegistered"},
            },
            {
                "status": "error",
                "message": "...",
                "details": {"error": "MessageRateExceeded"},
            },
        ]
    }
    assert _extract_dead_tokens(tokens, response) == ["ExponentPushToken[B]"]


def test_extract_dead_tokens_handles_shape_drift() -> None:
    """If Expo's response shape doesn't match what we sent (future API
    change, partial response), bail to [] rather than mis-clearing."""
    assert _extract_dead_tokens(["t"], {"data": "not-a-list"}) == []
    assert _extract_dead_tokens(["a", "b"], {"data": [{"status": "ok"}]}) == []
    assert _extract_dead_tokens(["a"], {}) == []


async def test_clear_dead_push_tokens_nulls_matching_users(
    db_session: AsyncSession,
) -> None:
    keep = await create_test_user(db_session, phone_number="+14155550701")
    keep.expo_push_token = "ExponentPushToken[ALIVE]"
    drop1 = await create_test_user(db_session, phone_number="+14155550702")
    drop1.expo_push_token = "ExponentPushToken[DEAD1]"
    drop2 = await create_test_user(db_session, phone_number="+14155550703")
    drop2.expo_push_token = "ExponentPushToken[DEAD2]"
    await db_session.commit()

    n = await clear_dead_push_tokens(
        db_session, ["ExponentPushToken[DEAD1]", "ExponentPushToken[DEAD2]"]
    )
    assert n == 2

    await db_session.refresh(keep)
    await db_session.refresh(drop1)
    await db_session.refresh(drop2)
    assert keep.expo_push_token == "ExponentPushToken[ALIVE]"
    assert drop1.expo_push_token is None
    assert drop2.expo_push_token is None


async def test_clear_dead_push_tokens_empty_short_circuits(
    db_session: AsyncSession,
) -> None:
    assert await clear_dead_push_tokens(db_session, []) == 0


async def test_send_notification_returns_dead_tokens_field(monkeypatch) -> None:
    """End-to-end: send_notification surfaces dead_tokens in its result
    so callers can fan them into `clear_dead_push_tokens`."""
    fake_response = {
        "data": [
            {
                "status": "error",
                "details": {"error": "DeviceNotRegistered"},
            }
        ]
    }

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return fake_response

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a) -> None:
            return None

        async def post(self, *args, **kwargs):
            return _FakeResponse()

    monkeypatch.setattr(
        "app.services.expo_notifications.httpx.AsyncClient",
        lambda: _FakeClient(),
    )

    result = await ExpoPushNotificationService.send_notification(
        push_tokens=["ExponentPushToken[DEAD]"],
        title="t",
        body="b",
    )
    assert result["status"] == "success"
    assert result["dead_tokens"] == ["ExponentPushToken[DEAD]"]


async def test_cascade_fan_out_clears_dead_tokens(
    db_session: AsyncSession,
) -> None:
    """End-to-end through the cascade fan-out: dead tokens get cleared
    as a side effect of the dispatch."""
    from app.services.notification_helpers import fan_out_cascade_notifications
    from app.services.sms_opt_out import OwnerImpact

    owner = await create_test_user(
        db_session, phone_number="+14155550800", full_name="Alice"
    )
    owner.expo_push_token = "ExponentPushToken[DEAD-X]"
    await db_session.commit()

    impact = OwnerImpact(
        owner=owner,
        contact_name="Bob",
        remaining_active_count=2,
        has_active_session=False,
        membership_id=uuid4(),
        status_changed_at=datetime.now(UTC),
    )

    # Send returns a result with dead_tokens — cascade should propagate.
    with patch(
        "app.services.notification_outbox.ExpoPushNotificationService.send_notification",
        new=AsyncMock(
            return_value={
                "status": "success",
                "data": {},
                "dead_tokens": ["ExponentPushToken[DEAD-X]"],
            }
        ),
    ):
        await fan_out_cascade_notifications(db_session, [impact])

    await db_session.refresh(owner)
    assert owner.expo_push_token is None

    # The clear happened on the outbox path (`_dispatch_push`'s dead-token
    # branch), which also records the push as terminally REFUSED — proving
    # the dispatch went through the reconciler, not a direct send.
    rows = (
        (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.recipient_user_id == owner.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].status == DeliveryStatus.REFUSED
    assert rows[0].last_error == "DeviceNotRegistered"
