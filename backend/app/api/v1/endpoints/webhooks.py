import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.models.processed_stripe_event import ProcessedStripeEvent
from app.models.subscription import (
    PlanType,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User as UserModel
from app.services import group_plan_service, subscription_service
from app.services.sub_lapse_notifications import Moment, notify_lapse
from app.utils.phone import format_to_e164

logger = logging.getLogger(__name__)


async def _safe_notify_lapse(
    db: AsyncSession, sub: Subscription, moment: Moment
) -> None:
    """Wrap notify_lapse so a dispatch failure can't 500 the webhook.

    Stripe retries on non-2xx. If notify_lapse raises (e.g., transient
    Twilio outage, missed FK lookup) and we let it propagate, the
    webhook 500s, Stripe retries, but the DB mutation has already
    committed inside the handler — `was_renewing` is now stale and
    the retry can't re-fire the notification.

    Better to log + ack so the dispatch failure surfaces in Bugsnag
    but the webhook contract holds.
    """
    try:
        await notify_lapse(db, sub, moment)
    except Exception:
        logger.exception(
            "sub_lapse_notify_dispatch_failed",
            extra={
                "subscription_id": str(sub.id),
                "moment": moment.value,
            },
        )


router = APIRouter()


# Inbound Stripe events. Mounted at the top-level /webhooks namespace (in
# main.py, outside the versioned /api/v1 client API) alongside delivery
# webhooks — these are server-to-server event sinks, not REST resources.
# Full path: /webhooks/payments/stripe
@router.post("/payments/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
):
    from app.services.stripe_service import construct_webhook_event

    payload = await request.body()
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing signature"
        )

    try:
        event = construct_webhook_event(payload, stripe_signature)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature"
        ) from None

    event_id = str(event.id)
    # Fast path: skip events we've already finished processing.
    existing = await db.execute(
        select(ProcessedStripeEvent).where(ProcessedStripeEvent.event_id == event_id)
    )
    if existing.scalar_one_or_none():
        logger.info("Skipping already-processed Stripe event: %s", event_id)
        return {"status": "ok"}

    # Claim the event by inserting the idempotency marker *before* running the
    # handler, and rely on the PK to abort duplicates. The marker is flushed
    # (not committed) so it commits in the SAME transaction as the handler's
    # effect: a concurrent/retried duplicate collides on the PK (→ skip), and a
    # crash can't leave the effect applied without the marker (or vice versa).
    # Stripe delivers at-least-once, so without this a duplicate could double-
    # grant (e.g. two gift subs for one payment).
    db.add(ProcessedStripeEvent(event_id=event_id, event_type=str(event.type)))
    try:
        await db.flush()
    except IntegrityError:
        # benign: idempotency race — a concurrent worker already stored this event
        await db.rollback()
        logger.info("Concurrent duplicate Stripe event skipped: %s", event_id)
        return {"status": "ok"}

    if event.type == "checkout.session.completed":
        session = event.data.object
        metadata = session.get("metadata", {})
        event_type = metadata.get("type")

        if event_type == "subscription":
            await _handle_subscription_checkout(db, session, metadata)
        elif event_type == "day_pass":
            await _handle_day_pass_checkout(db, session, metadata)
        elif event_type == "gift_subscription":
            result = await _handle_gift_checkout(db, session, metadata)
            if result:
                await db.commit()  # persist marker + gift effect atomically
                return result
        else:
            # Don't burn the idempotency marker on an event we ignore.
            await db.rollback()
            return {"status": "ignored"}

    elif event.type == "customer.subscription.updated":
        await _handle_subscription_updated(db, event.data.object)

    elif event.type == "customer.subscription.deleted":
        await _handle_subscription_deleted(db, event.data.object)

    elif event.type == "invoice.payment_succeeded":
        await _handle_invoice_paid(db, event.data.object)

    elif event.type == "invoice.payment_failed":
        invoice = event.data.object
        logger.warning(
            "Invoice payment failed: customer=%s, subscription=%s",
            invoice.get("customer"),
            invoice.get("subscription"),
        )
        await _maybe_notify_dunning_exhausted(db, invoice)

    # Commit the marker (and any handler effect not already committed).
    await db.commit()

    return {"status": "ok"}


async def _handle_subscription_checkout(
    db: AsyncSession, session: dict, metadata: dict
) -> None:
    from app.models.subscription import GROUP_PLAN_TYPES

    user_id = metadata.get("user_id")
    plan_type = metadata.get("plan_type", "monthly")
    stripe_subscription_id = session.get("subscription")

    if not user_id:
        logger.warning("Stripe subscription checkout: missing user_id in metadata")
        return

    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("Stripe subscription checkout: user %s not found", user_id)
        return

    # Guard against out-of-order delivery: if Stripe already shows this
    # subscription cancelled (the deleted event was processed before this late
    # checkout.completed), don't create an ACTIVE local sub for it.
    if stripe_subscription_id:
        from app.services.stripe_service import get_subscription_status

        live_status = get_subscription_status(stripe_subscription_id)
        if live_status in ("canceled", "incomplete_expired"):
            logger.info(
                "Skipping checkout create — Stripe sub %s already %s",
                stripe_subscription_id,
                live_status,
            )
            return

    sub = await subscription_service.create_subscription(
        db,
        phone_number=user.phone_number,
        plan_type=plan_type,
        source=SubscriptionSource.STRIPE_WEB.value,
        user_id=user.id,
        stripe_checkout_session_id=session.get("id"),
        stripe_subscription_id=stripe_subscription_id,
        auto_renew=True,
    )

    if plan_type in {pt.value for pt in GROUP_PLAN_TYPES}:
        await group_plan_service.create_group_plan(
            db,
            owner=user,
            subscription_id=sub.id,
            max_members=settings.GROUP_PLAN_MAX_MEMBERS,
        )

    logger.info(
        "Subscription created via checkout: user=%s plan=%s sub=%s",
        user_id,
        plan_type,
        sub.id,
    )


async def _handle_day_pass_checkout(
    db: AsyncSession, session: dict, metadata: dict
) -> None:
    """Grant a 24h DAY_PASS subscription row on one-time payment success.

    Rides the normal check_access 'subscription' path — no special access
    logic anywhere else (flow-review 3.9).
    """
    from datetime import UTC, datetime, timedelta

    from app.crud.user import crud_user
    from app.models.subscription import PlanType

    user_id = metadata.get("user_id")
    if not user_id:
        logger.warning("Stripe day-pass webhook: missing user_id in metadata")
        return

    user = await crud_user.get(db, id=user_id)
    if not user:
        logger.warning("Stripe day-pass webhook: unknown user %s", user_id)
        return

    now = datetime.now(UTC)
    await subscription_service.create_subscription(
        db,
        phone_number=user.phone_number,
        plan_type=PlanType.DAY_PASS.value,
        source=SubscriptionSource.STRIPE_WEB.value,
        user_id=user.id,
        period_start=now,
        period_end=now + timedelta(hours=settings.DAY_PASS_HOURS),
        stripe_checkout_session_id=session.get("id"),
        auto_renew=False,
    )


async def _handle_gift_checkout(
    db: AsyncSession, session: dict, metadata: dict
) -> dict | None:
    from app.crud.phone_number import crud_phone_number as crud_pn
    from app.crud.user import crud_user

    recipient_phone = format_to_e164(metadata.get("recipient_phone", ""))
    plan_type = metadata.get("plan_type", "monthly")
    gifter_phone = format_to_e164(metadata.get("gifter_phone", ""))

    if not recipient_phone:
        logger.warning("Stripe webhook: invalid recipient phone")
        return {"status": "invalid_phone"}

    user = await crud_user.get_by_phone(db, phone_number=recipient_phone)

    recipient_phone_obj, _ = await crud_pn.get_or_create(db, number=recipient_phone)
    stack_start = await subscription_service.get_stack_start(db, recipient_phone_obj.id)

    sub = await subscription_service.create_subscription(
        db,
        phone_number=recipient_phone,
        plan_type=plan_type,
        source=SubscriptionSource.STRIPE_GIFT.value,
        user_id=user.id if user else None,
        period_start=stack_start,
        stripe_checkout_session_id=session.get("id"),
        auto_renew=False,
        gifted_by_phone=gifter_phone if gifter_phone else None,
    )

    if gifter_phone:
        try:
            from app.crud.sponsor import crud_sponsorship_request

            gifter_phone_obj, _ = await crud_pn.get_or_create(db, number=gifter_phone)
            pending_req = await crud_sponsorship_request.get_pending_for_pair(
                db,
                requester_phone_id=recipient_phone_obj.id,
                target_phone_id=gifter_phone_obj.id,
            )
            if pending_req:
                await crud_sponsorship_request.fulfill(
                    db, request=pending_req, subscription_id=sub.id
                )
        except Exception:
            logger.exception("Failed to fulfill sponsorship request")

    return None


async def _handle_subscription_updated(db: AsyncSession, sub_obj: dict) -> None:
    stripe_sub_id = sub_obj.get("id")
    if not stripe_sub_id:
        return

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        logger.warning("Subscription updated: %s not found locally", stripe_sub_id)
        return

    items = sub_obj.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id", "")
        from app.services.stripe_service import _build_price_map

        price_map = _build_price_map()
        for plan_type, pid in price_map.items():
            if pid == price_id:
                sub.plan_type = plan_type.value
                break

    current_period_end = sub_obj.get("current_period_end")
    if current_period_end:
        sub.current_period_end = datetime.fromtimestamp(current_period_end, tz=UTC)

    # Detect "user flipped to cancel-at-period-end" — was renewing, now
    # scheduled to end. That's the T=0 moment for dependents (group
    # members, sponsored beneficiary) per the deletion plan's notification
    # surface. Captured BEFORE we mutate `auto_renew` below so the
    # transition is detectable.
    was_renewing = sub.auto_renew
    cancel_at_period_end = sub_obj.get("cancel_at_period_end", False)
    sub.auto_renew = not cancel_at_period_end

    await db.commit()
    logger.info("Subscription updated: %s", stripe_sub_id)

    if was_renewing and cancel_at_period_end:
        await _safe_notify_lapse(db, sub, Moment.T_ZERO)


async def _handle_subscription_deleted(db: AsyncSession, sub_obj: dict) -> None:
    stripe_sub_id = sub_obj.get("id")
    if not stripe_sub_id:
        return

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        logger.warning("Subscription deleted: %s not found locally", stripe_sub_id)
        return

    sub.status = SubscriptionStatus.CANCELLED.value
    sub.auto_renew = False
    await db.commit()

    if sub.plan_type in (PlanType.GROUP_MONTHLY.value, PlanType.GROUP_ANNUAL.value):
        from app.crud.group_plan import crud_group_plan

        group_plan = await crud_group_plan.get_by_subscription(
            db, subscription_id=sub.id
        )
        if group_plan:
            await group_plan_service.grant_grace_period_to_members(
                db, group_plan, days=settings.GROUP_PLAN_GRACE_DAYS
            )

    logger.info("Subscription cancelled: %s", stripe_sub_id)
    # Sub has now actually ended (Stripe sends this on natural lapse or
    # final retry failure). Fire T=end so dependents get the "ended
    # today" notification — for group plans this lands alongside the
    # in-app grace-period clock the members already received.
    await _safe_notify_lapse(db, sub, Moment.T_END)


async def _maybe_notify_dunning_exhausted(db: AsyncSession, invoice: dict) -> None:
    """Fire T=0 notification when Stripe has exhausted retries.

    Stripe runs a multi-day dunning sequence after a payment failure
    (retry tomorrow, day-3, day-5, etc.). Each failed attempt produces
    an `invoice.payment_failed` event. We only want to notify dependents
    on the LAST one — signalled by `next_payment_attempt` being null
    (Stripe will not try again, the sub will be marked unpaid /
    cancelled imminently).

    Notifying on every retry would spam dependents during a transient
    card decline that gets resolved on day 2.
    """
    if invoice.get("next_payment_attempt") is not None:
        return  # still in the retry window — wait for the final fail

    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        return

    await _safe_notify_lapse(db, sub, Moment.T_ZERO)


async def _handle_invoice_paid(db: AsyncSession, invoice: dict) -> None:
    stripe_sub_id = invoice.get("subscription")
    if not stripe_sub_id:
        return

    billing_reason = invoice.get("billing_reason")
    if billing_reason == "subscription_create":
        return

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return

    lines = invoice.get("lines", {}).get("data", [])
    if lines:
        period = lines[0].get("period", {})
        end = period.get("end")
        if end:
            sub.current_period_end = datetime.fromtimestamp(end, tz=UTC)

    sub.status = SubscriptionStatus.ACTIVE.value
    await db.commit()
    logger.info("Subscription renewed via invoice: %s", stripe_sub_id)
