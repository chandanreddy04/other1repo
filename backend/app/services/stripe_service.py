import logging

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.subscription import PlanType
from app.models.user import (
    STRIPE_CUSTOMER_PENDING_PREFIX,
    User,
    is_stripe_customer_pending,
)

stripe.api_key = settings.STRIPE_SECRET_KEY
logger = logging.getLogger(__name__)

_PRICE_ID_MAP: dict[PlanType, str] = {}


def _build_price_map() -> dict[PlanType, str]:
    return {
        PlanType.MONTHLY: settings.STRIPE_PRICE_ID_MONTHLY,
        PlanType.ANNUAL: settings.STRIPE_PRICE_ID_ANNUAL,
        PlanType.GROUP_MONTHLY: settings.STRIPE_PRICE_ID_GROUP_MONTHLY,
        PlanType.GROUP_ANNUAL: settings.STRIPE_PRICE_ID_GROUP_ANNUAL,
    }


def get_stripe_price_id(plan_type: PlanType) -> str:
    price_map = _build_price_map()
    price_id = price_map.get(plan_type, "")
    if not price_id:
        raise ValueError(
            f"No Stripe price ID configured for plan type: {plan_type.value}"
        )
    return price_id


def create_gift_checkout_session(
    recipient_phone: str,
    plan_type: str,
    gifter_phone: str,
    success_url: str,
    cancel_url: str,
    request_id: str | None = None,
) -> stripe.checkout.Session:
    price_id = (
        settings.STRIPE_PRICE_ID_MONTHLY
        if plan_type == "monthly"
        else settings.STRIPE_PRICE_ID_ANNUAL
    )

    metadata: dict[str, str] = {
        "recipient_phone": recipient_phone,
        "plan_type": plan_type,
        "gifter_phone": gifter_phone,
        "type": "gift_subscription",
    }
    if request_id:
        metadata["request_id"] = request_id

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
    )
    return session


async def get_or_create_stripe_customer(db: AsyncSession, user: User) -> str:
    if not is_stripe_customer_pending(user.stripe_customer_id):
        return user.stripe_customer_id

    try:
        customer = stripe.Customer.create(
            phone=user.phone_number,
            metadata={"user_id": str(user.id)},
            idempotency_key=f"customer:{user.id}",
        )
        user.stripe_customer_id = customer.id
        await db.commit()
        await db.refresh(user)
        logger.info("Created Stripe customer %s for user %s", customer.id, user.id)
        return customer.id
    except stripe.StripeError:
        # benign: the caller gets the pending placeholder and the worker's
        # retry_pending_stripe_customers reports one summary event per run
        logger.warning(
            "Stripe customer creation failed for user %s", user.id, exc_info=True
        )
        return user.stripe_customer_id


async def retry_pending_stripe_customers(db: AsyncSession) -> int:
    result = await db.execute(
        select(User).where(
            User.stripe_customer_id.startswith(STRIPE_CUSTOMER_PENDING_PREFIX)
        )
    )
    pending_users = result.scalars().all()
    resolved = 0

    for user in pending_users:
        customer_id = await get_or_create_stripe_customer(db, user)
        if not is_stripe_customer_pending(customer_id):
            resolved += 1

    failed = len(pending_users) - resolved
    if failed:
        # One event per run, not one per pending user (an outage would otherwise
        # emit N events every 10 minutes).
        logger.error(
            "stripe_customer_retry_failed",
            extra={
                "failed": failed,
                "pending": len(pending_users),
                "resolved": resolved,
            },
        )
    return resolved


# Stripe return URLs (success/cancel/portal) live on SHORT_DOMAIN, not
# APP_DOMAIN: the short-link host is the one the app claims as a universal
# link / app link (`CLAIMED_APP_PATHS` in app/web/short_links.py, the
# `associatedDomains` / intentFilters hosts in mobile/app.config.js). Both
# hosts serve the same backend. A return MAY hand back to the app (the OS
# often won't for a script-driven redirect); the app's confirming step and
# its foreground re-check are the reliable unlock path either way.
def create_subscription_checkout_session(
    customer_id: str,
    plan_type: PlanType,
    user_id: str,
) -> stripe.checkout.Session:
    price_id = get_stripe_price_id(plan_type)
    metadata = {
        "type": "subscription",
        "user_id": user_id,
        "plan_type": plan_type.value,
    }
    return stripe.checkout.Session.create(
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.SHORT_DOMAIN}/plans?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.SHORT_DOMAIN}/plans?checkout=canceled",
        metadata=metadata,
        subscription_data={"metadata": metadata},
        allow_promotion_codes=False,
    )


def create_day_pass_checkout_session(
    customer_id: str,
    user_id: str,
) -> stripe.checkout.Session:
    """One-time $0.99 pass covering DAY_PASS_HOURS (flow-review 3.9).

    mode=payment (not subscription); the webhook grants a DAY_PASS
    Subscription row on checkout.session.completed.
    """
    return stripe.checkout.Session.create(
        customer=customer_id,
        line_items=[{"price": settings.STRIPE_PRICE_ID_DAY_PASS, "quantity": 1}],
        mode="payment",
        success_url=f"{settings.SHORT_DOMAIN}/plans?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.SHORT_DOMAIN}/plans?checkout=canceled",
        metadata={"type": "day_pass", "user_id": user_id},
        allow_promotion_codes=False,
    )


def create_portal_session(
    customer_id: str, return_url: str | None = None
) -> stripe.billing_portal.Session:
    """Create a Stripe billing portal session.

    `return_url` overrides the default (/subscription) for callers that land
    the user on a non-app page after they're done — notably the public
    /sponsorships management flow, which routes back to
    /sponsorships?status=saved so we can render a "Changes saved" page
    instead of redirecting into the authenticated app surface.
    """
    return stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url or f"{settings.SHORT_DOMAIN}/subscription",
    )


def find_existing_customer_by_phone(phone_e164: str) -> stripe.Customer | None:
    """Find a Stripe Customer whose `phone` field matches.

    Used at re-signup to re-attach a Customer left behind by a prior
    soft-delete + hard-purge: the link from our user row was severed
    (`purged:<uuid>` sentinel) but the Customer entity stays in Stripe
    for tax retention. Re-attachment preserves payment history.

    Uses the Stripe Customer Search API; falls back to None on any
    API failure so a transient Stripe outage doesn't block signup.
    Returns the first match (the project's existing Customer creation
    is idempotent per-user_id, so duplicates are rare; if they exist,
    the most recent one is the right choice from a payment-continuity
    standpoint and Stripe's search returns recent results first).
    """
    try:
        result = stripe.Customer.search(query=f"phone:'{phone_e164}'", limit=1)
    except stripe.StripeError as exc:
        logger.exception("stripe_customer_search_failed", extra={"error": str(exc)})
        return None
    matches = result.get("data", [])
    if not matches:
        return None
    return matches[0]


def customer_has_subscription_history(stripe_customer_id: str) -> bool:
    """True if this Stripe Customer has ever had a subscription.

    Used to decide whether a re-signed-up user should be denied the
    free-trial branch in subscription access. Lists ALL statuses (active,
    canceled, incomplete, etc.) — any prior sub means the user has
    billed before. Falls back to False on Stripe error so a transient
    outage doesn't accidentally deny access to a legitimate brand-new
    user.
    """
    try:
        result = stripe.Subscription.list(
            customer=stripe_customer_id, status="all", limit=1
        )
    except stripe.StripeError as exc:
        logger.exception(
            "stripe_subscription_list_failed",
            extra={"customer_id": stripe_customer_id, "error": str(exc)},
        )
        return False
    return bool(result.get("data"))


def get_subscription_status(stripe_subscription_id: str) -> str | None:
    """Live status of a Stripe subscription, or None on error/absence.

    Used to guard against out-of-order webhook delivery (a checkout.completed
    arriving after the subscription was already cancelled). None on error so a
    transient outage doesn't block legitimate subscription creation.
    """
    try:
        sub = stripe.Subscription.retrieve(stripe_subscription_id)
    except stripe.StripeError as exc:
        logger.exception(
            "stripe_subscription_retrieve_failed",
            extra={"subscription_id": stripe_subscription_id, "error": str(exc)},
        )
        return None
    return sub.get("status")


def list_active_subscriptions(stripe_customer_id: str) -> list:
    """Active Stripe subscriptions for a customer (used for reconciliation).

    Returns [] on any Stripe error so a transient outage can't break access
    checks — the caller falls back to denying, same as before.
    """
    try:
        result = stripe.Subscription.list(
            customer=stripe_customer_id, status="active", limit=10
        )
    except stripe.StripeError as exc:
        logger.exception(
            "stripe_active_subscription_list_failed",
            extra={"customer_id": stripe_customer_id, "error": str(exc)},
        )
        return []
    return result.get("data", [])


def cancel_subscription_at_period_end(stripe_subscription_id: str) -> None:
    """Flag a subscription to stop renewing at the current period end.

    No refund, no proration — service continues through the paid period.
    Idempotent on Stripe's side: re-setting the flag is a no-op.

    Raises stripe.StripeError on API failure; callers decide whether to
    surface that or absorb it (e.g. the deletion orchestrator does NOT
    abort a soft-delete just because one Stripe call failed — the worker
    tick will re-attempt at hard-purge time).
    """
    stripe.Subscription.modify(
        stripe_subscription_id,
        cancel_at_period_end=True,
    )


def reactivate_subscription(stripe_subscription_id: str) -> None:
    """Undo a `cancel_at_period_end=True` flag — the subscription will
    keep renewing.

    Idempotent: clearing the flag on a sub that wasn't scheduled is a
    no-op. Used by `record_opt_in` to undo cancellations that the
    SMS-unsubscribe worker triggered when the user texts START — so
    `STOP -> auto-cancel -> START` returns the user to the state they
    were in before STOP, no more no less.

    Raises stripe.StripeError on API failure.
    """
    stripe.Subscription.modify(
        stripe_subscription_id,
        cancel_at_period_end=False,
    )


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
