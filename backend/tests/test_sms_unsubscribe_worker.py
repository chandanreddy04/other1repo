"""Tests for the worker auto-cancellation of stale SMS unsubscribes.

When a user texts STOP and ignores the consequence for the full grace
window (14 days by default), the worker:
  - cancels their Stripe subscription at period-end (if any)
  - sends a confirmation push
  - stamps `users.sms_unsubscribe_handled_at` so we don't repeat
A subsequent START clears the stamp so a future cycle works.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import sms_opt_out
from app.services.sms_unsubscribe_tasks import (
    process_unhandled_sms_unsubscribes,
)
from tests.helpers import create_test_subscription, create_test_user

pytestmark = pytest.mark.asyncio


async def _backdate_opt_out(db: AsyncSession, phone: str, days: int) -> None:
    """Pretend the user texted STOP `days` ago."""
    from app.crud.phone_number import crud_phone_number

    pn, _ = await crud_phone_number.get_or_create(db, number=phone)
    pn.sms_opted_out_at = datetime.now(UTC) - timedelta(days=days)
    pn.sms_opt_out_source = "test"
    await db.commit()


async def test_processes_user_past_grace_window(
    db_session: AsyncSession,
) -> None:
    user = await create_test_user(db_session, phone_number="+13105550401")
    user.expo_push_token = "ExponentPushToken[U]"
    sub = await create_test_subscription(db_session, user)
    sub.stripe_subscription_id = "sub_test_401"
    await db_session.commit()
    await _backdate_opt_out(db_session, "+13105550401", days=15)

    with patch(
        "app.services.sms_unsubscribe_tasks.stripe_service."
        "cancel_subscription_at_period_end"
    ) as mock_cancel, patch(
        "app.services.sms_unsubscribe_tasks."
        "send_account_holder_subscription_cancelled",
        new=AsyncMock(),
    ) as mock_push:
        processed = await process_unhandled_sms_unsubscribes(db_session)

    assert processed == 1
    mock_cancel.assert_called_once_with("sub_test_401")
    mock_push.assert_awaited_once()
    await db_session.refresh(user)
    assert user.sms_unsubscribe_handled_at is not None
    await db_session.refresh(sub)
    assert sub.auto_renew is False


async def test_skips_user_within_grace_window(
    db_session: AsyncSession,
) -> None:
    user = await create_test_user(db_session, phone_number="+13105550402")
    user.expo_push_token = "ExponentPushToken[U]"
    await create_test_subscription(db_session, user)
    await _backdate_opt_out(db_session, "+13105550402", days=3)

    with patch(
        "app.services.sms_unsubscribe_tasks.stripe_service."
        "cancel_subscription_at_period_end"
    ) as mock_cancel, patch(
        "app.services.sms_unsubscribe_tasks."
        "send_account_holder_subscription_cancelled",
        new=AsyncMock(),
    ) as mock_push:
        processed = await process_unhandled_sms_unsubscribes(db_session)

    assert processed == 0
    mock_cancel.assert_not_called()
    mock_push.assert_not_called()


async def test_skips_already_handled_user(db_session: AsyncSession) -> None:
    user = await create_test_user(db_session, phone_number="+13105550403")
    await create_test_subscription(db_session, user)
    await _backdate_opt_out(db_session, "+13105550403", days=20)
    user.sms_unsubscribe_handled_at = datetime.now(UTC) - timedelta(days=5)
    await db_session.commit()

    with patch(
        "app.services.sms_unsubscribe_tasks.stripe_service."
        "cancel_subscription_at_period_end"
    ) as mock_cancel, patch(
        "app.services.sms_unsubscribe_tasks."
        "send_account_holder_subscription_cancelled",
        new=AsyncMock(),
    ) as mock_push:
        processed = await process_unhandled_sms_unsubscribes(db_session)

    assert processed == 0
    mock_cancel.assert_not_called()
    mock_push.assert_not_called()


async def test_processes_user_with_no_active_subscription(
    db_session: AsyncSession,
) -> None:
    """No sub to cancel, so no push — only the handled stamp."""
    user = await create_test_user(db_session, phone_number="+13105550404")
    user.expo_push_token = "ExponentPushToken[U]"
    await db_session.commit()
    await _backdate_opt_out(db_session, "+13105550404", days=20)

    with patch(
        "app.services.sms_unsubscribe_tasks.stripe_service."
        "cancel_subscription_at_period_end"
    ) as mock_cancel, patch(
        "app.services.sms_unsubscribe_tasks."
        "send_account_holder_subscription_cancelled",
        new=AsyncMock(),
    ) as mock_push:
        processed = await process_unhandled_sms_unsubscribes(db_session)

    assert processed == 1
    mock_cancel.assert_not_called()
    mock_push.assert_not_called()


async def test_start_clears_handled_stamp_for_next_cycle(
    db_session: AsyncSession,
) -> None:
    """A user who texts START after being auto-cancelled gets their
    handled stamp cleared — so if they later STOP again, the worker
    will act again."""
    user = await create_test_user(db_session, phone_number="+13105550405")
    user.sms_unsubscribe_handled_at = datetime.now(UTC) - timedelta(days=2)
    await _backdate_opt_out(db_session, "+13105550405", days=20)

    await sms_opt_out.record_opt_in(db_session, "+13105550405")
    await db_session.refresh(user)
    assert user.sms_unsubscribe_handled_at is None


async def test_start_after_auto_cancel_restores_stripe_and_local_state(
    db_session: AsyncSession,
) -> None:
    """STOP -> worker auto-cancels -> START. The user's Stripe sub
    should be un-cancelled (reactivate API), `auto_renew` flipped back
    to True, and the `cancelled_by_sms_unsubscribe_at` stamp cleared.
    Net effect: state is what it was before STOP, no more no less."""
    from datetime import UTC, datetime

    user = await create_test_user(db_session, phone_number="+13105550500")
    sub = await create_test_subscription(db_session, user)
    sub.stripe_subscription_id = "sub_test_500"
    sub.auto_renew = False
    sub.cancelled_by_sms_unsubscribe_at = datetime.now(UTC)
    user.sms_unsubscribe_handled_at = datetime.now(UTC)
    await _backdate_opt_out(db_session, "+13105550500", days=20)

    with patch(
        "app.services.stripe_service.reactivate_subscription"
    ) as mock_reactivate:
        await sms_opt_out.record_opt_in(db_session, "+13105550500")

    mock_reactivate.assert_called_once_with("sub_test_500")
    await db_session.refresh(sub)
    assert sub.auto_renew is True
    assert sub.cancelled_by_sms_unsubscribe_at is None
    await db_session.refresh(user)
    assert user.sms_unsubscribe_handled_at is None


async def test_start_does_not_restore_subs_user_cancelled_themselves(
    db_session: AsyncSession,
) -> None:
    """A subscription the user cancelled via Stripe portal (so
    cancelled_by_sms_unsubscribe_at is NULL) must NOT be reactivated
    on START — we'd be re-enabling something they explicitly cancelled."""
    user = await create_test_user(db_session, phone_number="+13105550501")
    sub = await create_test_subscription(db_session, user)
    sub.stripe_subscription_id = "sub_test_501"
    sub.auto_renew = False  # user cancelled manually
    sub.cancelled_by_sms_unsubscribe_at = None  # not our doing
    await _backdate_opt_out(db_session, "+13105550501", days=20)

    with patch(
        "app.services.stripe_service.reactivate_subscription"
    ) as mock_reactivate:
        await sms_opt_out.record_opt_in(db_session, "+13105550501")

    mock_reactivate.assert_not_called()
    await db_session.refresh(sub)
    assert sub.auto_renew is False
    assert sub.cancelled_by_sms_unsubscribe_at is None


async def test_worker_stamps_cancelled_by_sms_unsubscribe_at(
    db_session: AsyncSession,
) -> None:
    """The stamp is what links the cancellation to the SMS opt-out
    cycle — verify the worker sets it when it cancels."""
    user = await create_test_user(db_session, phone_number="+13105550502")
    user.expo_push_token = "ExponentPushToken[X]"
    sub = await create_test_subscription(db_session, user)
    sub.stripe_subscription_id = "sub_test_502"
    await db_session.commit()
    await _backdate_opt_out(db_session, "+13105550502", days=20)

    with patch(
        "app.services.sms_unsubscribe_tasks.stripe_service."
        "cancel_subscription_at_period_end"
    ), patch(
        "app.services.sms_unsubscribe_tasks."
        "send_account_holder_subscription_cancelled",
        new=AsyncMock(),
    ):
        await process_unhandled_sms_unsubscribes(db_session)

    await db_session.refresh(sub)
    assert sub.cancelled_by_sms_unsubscribe_at is not None
    assert sub.auto_renew is False


async def test_soft_deleted_user_skipped(db_session: AsyncSession) -> None:
    """Users mid-account-deletion are out of scope — their subscription
    is being handled by the deletion orchestrator separately."""
    user = await create_test_user(db_session, phone_number="+13105550406")
    user.deleted_at = datetime.now(UTC) - timedelta(days=1)
    await create_test_subscription(db_session, user)
    await _backdate_opt_out(db_session, "+13105550406", days=20)
    await db_session.commit()

    with patch(
        "app.services.sms_unsubscribe_tasks.stripe_service."
        "cancel_subscription_at_period_end"
    ) as mock_cancel:
        processed = await process_unhandled_sms_unsubscribes(db_session)

    assert processed == 0
    mock_cancel.assert_not_called()
