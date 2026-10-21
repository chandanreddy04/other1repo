"""Tests for the cascade notification chooser and soft-stop renderer.

`fan_out_cascade_notifications` picks between CONTACT_OPTED_OUT,
CIRCLE_EMPTIED, and CIRCLE_EMPTIED_MID_SESSION based on what's left in
the owner's circle and whether they're mid-session. `render_soft_stop_gate`
picks 1c case A-E from a SenderProfile.

Related: app/services/notification_helpers.py, app/services/sms_opt_out.py.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import (
    DeliveryChannel,
    NotificationDelivery,
    NotificationKind,
)
from app.services.notification_helpers import (
    _cascade_kind,
    fan_out_cascade_notifications,
    render_soft_stop_gate,
)
from app.services.sms import SMSProvider, SMSResult
from app.services.sms_opt_out import OwnerImpact, SenderProfile
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _impact(
    owner,
    contact_name: str = "Bob",
    remaining: int = 0,
    active_session: bool = False,
) -> OwnerImpact:
    return OwnerImpact(
        owner=owner,
        contact_name=contact_name,
        remaining_active_count=remaining,
        has_active_session=active_session,
        active_session_id=uuid4() if active_session else None,
        membership_id=uuid4(),
        status_changed_at=datetime.now(UTC),
    )


async def _rows(db, owner_id, kind) -> list[NotificationDelivery]:
    return list(
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.recipient_user_id == owner_id,
                    NotificationDelivery.kind == kind,
                )
            )
        )
        .scalars()
        .all()
    )


# The cascade now enqueues delivery rows the reconciler dispatches (defect 5);
# these patches keep the inline send from touching real providers.
_NO_PROVIDERS = (
    patch(
        "app.services.notification_outbox.ExpoPushNotificationService.send_notification",
        new_callable=AsyncMock,
        return_value={"ok_tokens": [], "dead_tokens": [], "ticket_ids": {}},
    ),
    patch(
        "app.services.notification_outbox.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
        return_value=SMSResult(
            success=True, message_id="SM_cascade", provider=SMSProvider.TWILIO
        ),
    ),
)


async def test_chooser_kind_selection() -> None:
    """The kind chooser: remaining>0 → opted-out; empty+no-session → emptied;
    empty+active → mid-session."""
    o = object()
    assert (
        _cascade_kind(_impact(o, remaining=2, active_session=False))
        is NotificationKind.CONTACT_OPTED_OUT
    )
    assert (
        _cascade_kind(_impact(o, remaining=0, active_session=False))
        is NotificationKind.CIRCLE_EMPTIED
    )
    assert (
        _cascade_kind(_impact(o, remaining=0, active_session=True))
        is NotificationKind.CIRCLE_EMPTIED_MID_SESSION
    )


async def test_enqueues_contact_opted_out_when_remaining(
    db_session: AsyncSession,
) -> None:
    owner = await create_test_user(db_session, phone_number="+13105550001")
    with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
        await fan_out_cascade_notifications(
            db_session, [_impact(owner, remaining=2, active_session=False)]
        )
    assert await _rows(db_session, owner.id, NotificationKind.CONTACT_OPTED_OUT)
    assert not await _rows(db_session, owner.id, NotificationKind.CIRCLE_EMPTIED)


async def test_enqueues_emptied_no_session(db_session: AsyncSession) -> None:
    owner = await create_test_user(db_session, phone_number="+13105550002")
    with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
        await fan_out_cascade_notifications(
            db_session, [_impact(owner, remaining=0, active_session=False)]
        )
    rows = await _rows(db_session, owner.id, NotificationKind.CIRCLE_EMPTIED)
    assert rows and all(r.channel == DeliveryChannel.PUSH for r in rows)


async def test_enqueues_emptied_mid_session_push_and_sms(
    db_session: AsyncSession,
) -> None:
    from datetime import UTC, datetime, timedelta

    from app.models.session import Session, SessionStatus, SessionType

    owner = await create_test_user(db_session, phone_number="+13105550003")
    session = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN.value,
        expected_return_time=datetime.now(UTC) + timedelta(hours=1),
        status=SessionStatus.ACTIVE.value,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    impact = OwnerImpact(
        owner=owner,
        contact_name="Bob",
        remaining_active_count=0,
        has_active_session=True,
        active_session_id=session.id,
        membership_id=uuid4(),
        status_changed_at=datetime.now(UTC),
    )
    with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
        await fan_out_cascade_notifications(db_session, [impact])
    # Query by session (the SMS row is keyed by phone id, not user id).
    rows = list(
        (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.session_id == session.id,
                    NotificationDelivery.kind
                    == NotificationKind.CIRCLE_EMPTIED_MID_SESSION,
                )
            )
        )
        .scalars()
        .all()
    )
    # Urgent → push + SMS backup (per policy).
    assert {r.channel for r in rows} == {
        DeliveryChannel.PUSH,
        DeliveryChannel.SMS,
    }


async def test_inline_send_failure_still_enqueues(
    db_session: AsyncSession,
) -> None:
    """enqueue_and_send swallows an inline-send error so the webhook can't 500
    back to Twilio; the rows are committed and the tick retries them."""
    owner = await create_test_user(db_session, phone_number="+13105550100")
    with patch(
        "app.services.notification_outbox.send_due_deliveries",
        new=AsyncMock(side_effect=RuntimeError("provider down")),
    ):
        await fan_out_cascade_notifications(
            db_session, [_impact(owner, remaining=2, active_session=False)]
        )
    # Rows survived the failed inline send.
    assert await _rows(db_session, owner.id, NotificationKind.CONTACT_OPTED_OUT)


async def test_idempotent_on_webhook_retry(db_session: AsyncSession) -> None:
    """A Twilio webhook retry re-derives the same impact; the dedupe key means
    no duplicate rows."""
    owner = await create_test_user(db_session, phone_number="+13105550101")
    impact = _impact(owner, remaining=2, active_session=False)
    with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
        await fan_out_cascade_notifications(db_session, [impact])
        await fan_out_cascade_notifications(db_session, [impact])
    rows = await _rows(db_session, owner.id, NotificationKind.CONTACT_OPTED_OUT)
    assert len(rows) == 1


async def test_render_soft_stop_picks_single_owner(db_session: AsyncSession) -> None:
    body = render_soft_stop_gate(
        SenderProfile(owner_names=["Alice"], owner_count=1, has_account=False)
    )
    # Gate A names the (single) owner — owner-approved 2026-09-27.
    assert "Alice" in body
    assert "Alice's Circle of Trust" in body
    assert "STOP to confirm" in body


async def test_render_soft_stop_picks_multi_owner() -> None:
    body = render_soft_stop_gate(
        SenderProfile(owner_names=[], owner_count=3, has_account=False)
    )
    assert "3 people" in body
    assert "STOP to confirm" in body


async def test_render_soft_stop_picks_account_only() -> None:
    body = render_soft_stop_gate(
        SenderProfile(owner_names=[], owner_count=0, has_account=True)
    )
    assert "sign-in codes" in body


async def test_render_soft_stop_picks_account_and_contact() -> None:
    body = render_soft_stop_gate(
        SenderProfile(owner_names=[], owner_count=2, has_account=True)
    )
    assert "2 people" in body
    assert "sign-in codes" in body


async def test_render_soft_stop_picks_generic() -> None:
    body = render_soft_stop_gate(SenderProfile())
    assert "Did you mean to opt out" in body
