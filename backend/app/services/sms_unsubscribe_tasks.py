"""Worker-tick handling of long-term SMS opt-outs from account holders.

When a Made It Home user texts STOP, we immediately push them ("you've
unsubscribed from us") via `send_account_holder_unsubscribed`. If they
ignore it for `SMS_UNSUBSCRIBE_GRACE_DAYS`, this module:

  - cancels their active, auto-renewing, self-paid Stripe subscription
    at period-end, if they have one (service continues until their next
    billing date, then doesn't renew)
  - sends them the confirmation push, ONLY when a subscription was
    actually set to cancel — a user with no such subscription (free
    trial, sponsored/gift, group-plan member) has nothing to confirm
  - stamps `users.sms_unsubscribe_handled_at` either way, so the worker
    doesn't re-act on the same opt-out cycle

When the user texts START, `sms_opt_out.record_opt_in` clears
`sms_unsubscribe_handled_at` so a future STOP gets a fresh grace
clock.

Related: services/sms_opt_out.py (state engine + restore on START),
         api/v1/endpoints/inbound_sms.py (T=0 push trigger),
         services/notification_helpers.py (push templates).
"""

import logging
from datetime import UTC, datetime, timedelta

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.phone_number import PhoneNumber
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services import stripe_service
from app.services.notification_helpers import (
    send_account_holder_subscription_cancelled,
)

logger = logging.getLogger(__name__)


async def process_unhandled_sms_unsubscribes(db: AsyncSession) -> int:
    """Act on every account holder who's been SMS-unsubscribed for the
    full grace window without responding. Returns the count of users
    processed (subscription cancelled + push sent).

    Idempotent within a tick AND across ticks — `sms_unsubscribe_handled_at`
    on the User row stops a second action. The query's partial index on
    that column keeps the scan O(unhandled).
    """
    grace_days = settings.SMS_UNSUBSCRIBE_GRACE_DAYS
    cutoff = datetime.now(UTC) - timedelta(days=grace_days)

    # Users whose phone has been opted-out since before the cutoff,
    # haven't been handled yet, and aren't already soft-deleted.
    q = (
        select(User)
        .join(PhoneNumber, User.phone_number_id == PhoneNumber.id)
        .where(
            PhoneNumber.sms_opted_out_at.is_not(None),
            PhoneNumber.sms_opted_out_at <= cutoff,
            User.sms_unsubscribe_handled_at.is_(None),
            User.deleted_at.is_(None),
        )
    )
    user_ids = [u.id for u in (await db.execute(q)).scalars().all()]
    if not user_ids:
        return 0

    processed = 0
    now = datetime.now(UTC)
    for user_id in user_ids:
        # Re-`get` per user: a rollback below expires every loaded
        # instance, and an expired attribute can't lazy-load in async.
        user = await db.get(User, user_id)
        if user is None:
            continue
        try:
            await _act_on_unsubscribed_user(db, user, grace_days)
            user.sms_unsubscribe_handled_at = now
            # Commit per user so a later user's failure (and the rollback
            # it needs) can't discard this user's stamp + auto_renew flip.
            await db.commit()
            processed += 1
        except Exception:
            logger.exception(
                "sms_unsubscribe_handler_failed",
                extra={"user_id": str(user_id)},
            )
            # Don't stamp `handled_at` — leave them for the next tick. The
            # push enqueue (enqueue_and_send) writes to the DB, so a DB
            # error there aborts the transaction; roll back so the rest of
            # the tick (and its session) stays usable.
            await db.rollback()
    if processed:
        logger.info(
            "sms_unsubscribe_processed",
            extra={"count": processed, "grace_days": grace_days},
        )
    return processed


async def _act_on_unsubscribed_user(
    db: AsyncSession, user: User, grace_days: int
) -> None:
    """Cancel the user's active, auto-renewing, self-paid Stripe
    subscription at period-end (if there is one) and, only then, send the
    confirmation push. A user with no such subscription (free trial,
    sponsored/gift, group-plan member, or one that's already
    non-renewing) has nothing set to cancel, so no push is sent — there's
    nothing to confirm. The Stripe cancel raising, or the push failing to
    ENQUEUE (a DB error in `enqueue_and_send`), raises — the caller
    leaves `handled_at` NULL so the next tick retries. Once the row is
    enqueued via the outbox, a provider-side failure during the inline
    send is retried by the reconciler, not raised here — so a normal
    return (subscription cancelled + push enqueued, OR nothing to do)
    means the push is auditable, not necessarily delivered yet; the
    caller still stamps `handled_at` either way so the sweep doesn't
    retry forever for a user with no subscription."""

    # Cancel the active subscription if there is one and it's a
    # self-paid, auto-renewing Stripe subscription. A user with no such
    # sub (paid up via gift, on free trial, in a group plan, etc.) has
    # nothing to cancel.
    sub_q = select(Subscription).where(
        Subscription.user_id == user.id,
        Subscription.status == SubscriptionStatus.ACTIVE.value,
    )
    active_sub = (await db.execute(sub_q)).scalar_one_or_none()
    sub_to_flip: Subscription | None = None
    if (
        active_sub is not None
        and active_sub.stripe_subscription_id
        and active_sub.auto_renew
    ):
        try:
            stripe_service.cancel_subscription_at_period_end(
                active_sub.stripe_subscription_id
            )
        except stripe.StripeError:
            logger.exception(
                "sms_unsubscribe_stripe_cancel_failed",
                extra={
                    "user_id": str(user.id),
                    "stripe_subscription_id": active_sub.stripe_subscription_id,
                },
            )
            raise
        # Defer the local auto_renew flip until after the confirmation
        # push lands. Stripe's cancel is idempotent (per its docstring),
        # so a retry will re-cancel safely; but if we flipped auto_renew
        # here and the push then failed, the parent's commit would
        # persist auto_renew=False while leaving handled_at NULL — the
        # next tick would re-send the push to a user whose sub looks
        # locally-cancelled. Deferring keeps the local + push state in
        # sync.
        sub_to_flip = active_sub

    if sub_to_flip is None:
        # Nothing was set to cancel — no push to send. The caller still
        # stamps `handled_at` on this normal return.
        return

    await send_account_holder_subscription_cancelled(
        db, user, grace_days, subscription_id=sub_to_flip.id
    )

    sub_to_flip.auto_renew = False
    # Stamp so record_opt_in can find this sub and reverse the
    # cancellation if the user later texts START. We only un-
    # cancel subs we cancelled — never ones the user requested
    # via Stripe portal manually.
    sub_to_flip.cancelled_by_sms_unsubscribe_at = datetime.now(UTC)
