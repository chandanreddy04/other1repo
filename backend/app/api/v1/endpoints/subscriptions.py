import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import get_current_user_with_profile
from app.api.v1.deps.db import get_db
from app.core.errors import UpstreamUnavailable
from app.models.subscription import PlanType
from app.models.user import User as UserModel
from app.models.user import is_stripe_customer_pending
from app.schemas.subscription import (
    CheckoutRequest,
    CheckoutResponse,
    PortalResponse,
    SubscriptionStatusResponse,
    SubscriptionUpdateRequest,
)
from app.services import subscription_service
from app.services.stripe_service import (
    cancel_subscription_at_period_end,
    create_day_pass_checkout_session,
    create_portal_session,
    create_subscription_checkout_session,
    get_or_create_stripe_customer,
    reactivate_subscription,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    return await subscription_service.check_access(db, current_user)


@router.patch("", response_model=SubscriptionStatusResponse)
async def update_subscription(
    request: SubscriptionUpdateRequest,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's subscription renewal intent (native
    cancel / reactivate — the change-plan and payment-method flows stay on
    Stripe's hosted portal via POST /portal).

    The sole mutable field is `cancel_at_period_end`: True schedules a
    cancellation at the paid period end (service continues until then), False
    reactivates one previously scheduled to cancel. Only a self-paid recurring
    Stripe subscription is mutable here — gift / comp / day-pass access carry
    no recurring subscription to toggle (404).
    """
    sub = await subscription_service.get_cancelable_subscription(db, current_user.id)
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No manageable subscription found.",
        )

    try:
        if request.cancel_at_period_end:
            cancel_subscription_at_period_end(sub.stripe_subscription_id)
        else:
            reactivate_subscription(sub.stripe_subscription_id)
    except stripe.StripeError as e:
        logger.warning("Stripe subscription update failed: %s", e)
        raise UpstreamUnavailable(
            detail="Payment service temporarily unavailable."
        ) from e

    # Mirror Stripe's flag locally for instant UI feedback; the
    # customer.subscription.updated webhook re-affirms it idempotently.
    sub.auto_renew = not request.cancel_at_period_end
    await db.commit()

    return await subscription_service.check_access(db, current_user)


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    request: CheckoutRequest,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    try:
        plan_type = PlanType(request.plan_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid plan type: {request.plan_type}",
        ) from exc

    access = await subscription_service.check_access(db, current_user)
    if access.has_access and access.reason == "subscription":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active subscription.",
        )

    customer_id = await get_or_create_stripe_customer(db, current_user)
    if is_stripe_customer_pending(customer_id):
        raise UpstreamUnavailable(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Please try again in a moment.",
        )

    try:
        session = create_subscription_checkout_session(
            customer_id=customer_id,
            plan_type=plan_type,
            user_id=str(current_user.id),
        )
    except stripe.StripeError as e:
        logger.warning("Stripe checkout creation failed: %s", e)
        raise UpstreamUnavailable(
            detail="Payment service temporarily unavailable."
        ) from e

    return CheckoutResponse(checkout_url=session.url)


@router.post("/day-pass", response_model=CheckoutResponse)
async def create_day_pass(
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    """One-time $0.99 pass covering the next 24h (flow-review 3.9) —
    the episodic rung below a subscription for a single night out."""
    access = await subscription_service.check_access(db, current_user)
    if access.has_access and access.reason == "subscription":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active subscription.",
        )

    customer_id = await get_or_create_stripe_customer(db, current_user)
    if is_stripe_customer_pending(customer_id):
        raise UpstreamUnavailable(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Please try again in a moment.",
        )

    try:
        session = create_day_pass_checkout_session(
            customer_id=customer_id, user_id=str(current_user.id)
        )
    except stripe.StripeError as e:
        logger.warning("Stripe day-pass checkout creation failed: %s", e)
        raise UpstreamUnavailable(
            detail="Payment service temporarily unavailable."
        ) from e

    return CheckoutResponse(checkout_url=session.url)


@router.post("/portal", response_model=PortalResponse)
async def create_portal(
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    if is_stripe_customer_pending(current_user.stripe_customer_id):
        raise UpstreamUnavailable(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Please try again in a moment.",
        )

    try:
        session = create_portal_session(current_user.stripe_customer_id)
    except stripe.StripeError as e:
        logger.warning("Stripe portal creation failed: %s", e)
        raise UpstreamUnavailable(
            detail="Payment service temporarily unavailable."
        ) from e

    return PortalResponse(portal_url=session.url)
