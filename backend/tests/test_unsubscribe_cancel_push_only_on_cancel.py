"""O14: the "Subscription set to cancel" push fires only when a subscription
was actually set to cancel.

Before this fix, `_act_on_unsubscribed_user` sent
`account_holder_subscription_cancelled` to EVERY user past the SMS-unsubscribe
grace window, whether or not they had an active, auto-renewing, self-paid
Stripe subscription to cancel — contradicting its own copy ("...subscription
will end at your next billing date"). The fix only sends the push when
`sub_to_flip is not None` (a subscription was actually cancelled), while
still stamping `sms_unsubscribe_handled_at` either way so the sweep doesn't
retry forever for a user with nothing to cancel.

Related: app/services/sms_unsubscribe_tasks.py (_act_on_unsubscribed_user),
app/services/notification_constants.py
(ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED_*), docs/notifications.md (O14).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.models.subscription import SubscriptionSource
from app.services.sms_unsubscribe_tasks import process_unhandled_sms_unsubscribes
from tests.helpers import create_test_subscription, create_test_user

pytestmark = pytest.mark.asyncio


async def _backdate_opt_out(db: AsyncSession, phone: str, days: int) -> None:
    pn, _ = await crud_phone_number.get_or_create(db, number=phone)
    pn.sms_opted_out_at = datetime.now(UTC) - timedelta(days=days)
    pn.sms_opt_out_source = "test"
    await db.commit()


class TestPushOnlyWhenSubscriptionActuallyCancelled:
    async def test_self_paid_auto_renew_sub_gets_cancel_and_push(
        self, db_session: AsyncSession
    ) -> None:
        user = await create_test_user(db_session, phone_number="+14155599301")
        user.expo_push_token = "ExponentPushToken[A]"
        sub = await create_test_subscription(
            db_session, user, source=SubscriptionSource.STRIPE_WEB.value
        )
        sub.stripe_subscription_id = "sub_cancel_301"
        assert sub.auto_renew is True
        await db_session.commit()
        await _backdate_opt_out(db_session, "+14155599301", days=15)

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
        mock_cancel.assert_called_once_with("sub_cancel_301")
        mock_push.assert_awaited_once()
        await db_session.refresh(user)
        assert user.sms_unsubscribe_handled_at is not None
        await db_session.refresh(sub)
        assert sub.auto_renew is False
        assert sub.cancelled_by_sms_unsubscribe_at is not None

    async def test_no_active_subscription_gets_no_push_but_is_handled(
        self, db_session: AsyncSession
    ) -> None:
        """Free trial (no Subscription row at all)."""
        user = await create_test_user(db_session, phone_number="+14155599302")
        user.expo_push_token = "ExponentPushToken[B]"
        await db_session.commit()
        await _backdate_opt_out(db_session, "+14155599302", days=20)

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
        await db_session.refresh(user)
        assert user.sms_unsubscribe_handled_at is not None

    async def test_sponsored_gift_subscription_gets_no_push(
        self, db_session: AsyncSession
    ) -> None:
        """A gifted subscription has no `stripe_subscription_id` the user
        controls the way a self-paid one does in this flow — nothing of
        theirs is being set to cancel."""
        user = await create_test_user(db_session, phone_number="+14155599303")
        user.expo_push_token = "ExponentPushToken[C]"
        sub = await create_test_subscription(
            db_session, user, source=SubscriptionSource.STRIPE_GIFT.value
        )
        sub.stripe_subscription_id = None
        await db_session.commit()
        await _backdate_opt_out(db_session, "+14155599303", days=20)

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
        await db_session.refresh(user)
        assert user.sms_unsubscribe_handled_at is not None
        await db_session.refresh(sub)
        assert sub.cancelled_by_sms_unsubscribe_at is None

    async def test_already_non_renewing_sub_gets_no_push(
        self, db_session: AsyncSession
    ) -> None:
        """An ACTIVE subscription that's already `auto_renew=False` (e.g.
        already cancelled via the Stripe portal) has nothing left to set to
        cancel — same "no push" outcome as a group-plan dependent, who has
        no Subscription row of their own at all."""
        user = await create_test_user(db_session, phone_number="+14155599304")
        user.expo_push_token = "ExponentPushToken[D]"
        sub = await create_test_subscription(db_session, user)
        sub.stripe_subscription_id = "sub_norenew_304"
        sub.auto_renew = False
        await db_session.commit()
        await _backdate_opt_out(db_session, "+14155599304", days=20)

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
        await db_session.refresh(user)
        assert user.sms_unsubscribe_handled_at is not None
        await db_session.refresh(sub)
        assert sub.cancelled_by_sms_unsubscribe_at is None

    async def test_stripe_failure_stamps_nothing(
        self, db_session: AsyncSession
    ) -> None:
        """Existing contract, unchanged: a Stripe error raises, so the
        caller leaves `handled_at` NULL and the auto_renew flip never
        happens — the next tick retries."""
        user = await create_test_user(db_session, phone_number="+14155599305")
        user.expo_push_token = "ExponentPushToken[E]"
        sub = await create_test_subscription(db_session, user)
        sub.stripe_subscription_id = "sub_fail_305"
        await db_session.commit()
        await _backdate_opt_out(db_session, "+14155599305", days=20)

        with patch(
            "app.services.sms_unsubscribe_tasks.stripe_service."
            "cancel_subscription_at_period_end",
            side_effect=stripe.StripeError("boom"),
        ) as mock_cancel, patch(
            "app.services.sms_unsubscribe_tasks."
            "send_account_holder_subscription_cancelled",
            new=AsyncMock(),
        ) as mock_push:
            processed = await process_unhandled_sms_unsubscribes(db_session)

        assert processed == 0
        mock_cancel.assert_called_once_with("sub_fail_305")
        mock_push.assert_not_called()
        await db_session.refresh(user)
        assert user.sms_unsubscribe_handled_at is None
        await db_session.refresh(sub)
        assert sub.auto_renew is True
        assert sub.cancelled_by_sms_unsubscribe_at is None
