import logging
import secrets
import string
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.phone_number import crud_phone_number
from app.models.phone_number import PhoneNumber
from app.models.session import Session, SessionType
from app.models.subscription import (
    PlanType,
    Promotion,
    Referral,
    ReferralStatus,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User, is_stripe_customer_pending
from app.schemas.subscription import SubscriptionStatusResponse

logger = logging.getLogger(__name__)


def generate_share_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(8))


def generate_circle_invite_code() -> str:
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(8))


async def get_sessions_used_count(db: AsyncSession, user_id: UUID) -> int:
    """Count check-in sessions created by a user (drives free-trial gating).

    SOS sessions are excluded: SOS is free always, so a panic press must not
    consume the free-trial session a new user would otherwise use for their
    first check-in.
    """
    result = await db.execute(
        select(func.count())
        .select_from(Session)
        .where(
            Session.user_id == user_id,
            Session.session_type != SessionType.SOS,
        )
    )
    return result.scalar() or 0


def _plan_type_for_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    return {
        settings.STRIPE_PRICE_ID_MONTHLY: PlanType.MONTHLY.value,
        settings.STRIPE_PRICE_ID_ANNUAL: PlanType.ANNUAL.value,
        settings.STRIPE_PRICE_ID_GROUP_MONTHLY: PlanType.GROUP_MONTHLY.value,
        settings.STRIPE_PRICE_ID_GROUP_ANNUAL: PlanType.GROUP_ANNUAL.value,
    }.get(price_id)


async def reconcile_subscription_from_stripe(
    db: AsyncSession, user: User
) -> Subscription | None:
    """Backfill a paid Stripe subscription we never recorded (lost webhook).

    Bounded: only called from check_access when the user would otherwise be
    denied AND has a real (non-placeholder) Stripe customer — so it's not on the
    hot path for free users with access. Returns the created local sub, or None.
    """
    if not user.stripe_customer_id or is_stripe_customer_pending(
        user.stripe_customer_id
    ):
        return None

    from app.services.stripe_service import list_active_subscriptions

    for stripe_sub in list_active_subscriptions(user.stripe_customer_id):
        sub_id = stripe_sub.get("id")
        if not sub_id:
            continue
        existing = await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )
        if existing.scalar_one_or_none():
            continue

        items = (stripe_sub.get("items") or {}).get("data") or []
        item = items[0] if items else {}
        price_id = (item.get("price") or {}).get("id")
        plan_type = _plan_type_for_price(price_id)
        if not plan_type:
            continue

        # current_period_end moved from the subscription to the item on newer
        # Stripe API versions — read either.
        period_ts = stripe_sub.get("current_period_end") or item.get(
            "current_period_end"
        )
        period_end = datetime.fromtimestamp(period_ts, tz=UTC) if period_ts else None

        logger.error(
            "reconciled_missing_subscription",
            extra={"user_id": str(user.id), "stripe_subscription_id": sub_id},
        )
        return await create_subscription(
            db,
            phone_number=user.phone_number,
            plan_type=plan_type,
            source=SubscriptionSource.STRIPE_WEB.value,
            user_id=user.id,
            period_end=period_end,
            stripe_subscription_id=sub_id,
        )
    return None


async def check_access(db: AsyncSession, user: User) -> SubscriptionStatusResponse:
    now = datetime.now(UTC)

    # 1. Active subscription
    sub = await get_active_subscription(db, user.id)
    if sub:
        return SubscriptionStatusResponse(
            has_access=True,
            reason="subscription",
            expires_at=sub.current_period_end,
            plan_type=sub.plan_type,
            source=sub.source,
            cancel_at_period_end=not sub.auto_renew,
        )

    # 2. Active group plan membership
    from app.services.group_plan_service import get_group_plan_for_access_check

    group_result = await get_group_plan_for_access_check(db, user.id)
    if group_result:
        group_sub, group_plan = group_result
        return SubscriptionStatusResponse(
            has_access=True,
            reason="group_plan",
            expires_at=group_sub.current_period_end,
            plan_type=group_sub.plan_type,
            group_plan_id=group_plan.id,
            group_plan_owner_name=group_plan.owner.full_name,
            source=group_sub.source,
            # cancel_at_period_end intentionally omitted: a member manages
            # membership (leave), not the owner's billing renewal.
        )

    # 3. Active promotion
    if await is_promotion_active(db):
        return SubscriptionStatusResponse(
            has_access=True,
            reason="promotion",
        )

    # 4. Referral credit
    if user.free_credit_end and user.free_credit_end > now:
        return SubscriptionStatusResponse(
            has_access=True,
            reason="referral_credit",
            expires_at=user.free_credit_end,
        )

    # 5. Free trial (1 session) — denied if the user re-signed up
    # after a prior deletion + hard-purge cycle (re-attached Stripe
    # Customer with subscription history). See Phase 9 in
    # docs/account-deletion-plan.md.
    if not user.had_prior_billing_history:
        sessions_used = await get_sessions_used_count(db, user.id)
        if sessions_used < settings.FREE_TRIAL_SESSIONS:
            return SubscriptionStatusResponse(
                has_access=True,
                reason="free_trial",
                sessions_remaining=settings.FREE_TRIAL_SESSIONS - sessions_used,
            )

    # 6. Self-heal: a paid Stripe subscription whose webhook we never received
    # (charged but no local record). Only reached when otherwise fully denied.
    reconciled = await reconcile_subscription_from_stripe(db, user)
    if reconciled:
        return SubscriptionStatusResponse(
            has_access=True,
            reason="subscription",
            expires_at=reconciled.current_period_end,
            plan_type=reconciled.plan_type,
            source=reconciled.source,
            cancel_at_period_end=not reconciled.auto_renew,
        )

    # 7. No access
    return SubscriptionStatusResponse(
        has_access=False,
        reason="none",
        sessions_remaining=0,
    )


async def get_active_subscription(
    db: AsyncSession, user_id: UUID
) -> Subscription | None:
    now = datetime.now(UTC)
    result = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.current_period_end > now,
            )
        )
    )
    return result.scalar_one_or_none()


async def get_cancelable_subscription(
    db: AsyncSession, user_id: UUID
) -> Subscription | None:
    """The user's own active, self-paid recurring Stripe subscription — the
    only kind manageable in-app (cancel/reactivate).

    Excludes gift (STRIPE_GIFT), comp (COMP), and day-pass access: none of
    those carry a recurring `stripe_subscription_id` to toggle, and a gift/comp
    isn't the recipient's to cancel. A group OWNER's plan qualifies (it's their
    self-paid recurring sub); a group MEMBER has no own subscription so this
    returns None for them.
    """
    sub = await get_active_subscription(db, user_id)
    if (
        sub
        and sub.source == SubscriptionSource.STRIPE_WEB.value
        and sub.stripe_subscription_id
        and sub.plan_type != PlanType.DAY_PASS.value
    ):
        return sub
    return None


async def get_stack_start(db: AsyncSession, phone_number_id: UUID) -> datetime:
    """Return the start date for a new stacked subscription.

    If the recipient already has subscriptions that extend into the future,
    the new subscription starts when the furthest one ends (stacking).
    """
    now = datetime.now(UTC)
    result = await db.execute(
        select(func.max(Subscription.current_period_end)).where(
            Subscription.phone_number_id == phone_number_id,
            Subscription.current_period_end > now,
            Subscription.status.in_(
                [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.PENDING.value]
            ),
        )
    )
    furthest = result.scalar_one_or_none()
    return furthest if furthest else now


async def create_subscription(
    db: AsyncSession,
    phone_number: str,
    plan_type: str,
    source: str,
    user_id: UUID | None = None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    stripe_checkout_session_id: str | None = None,
    stripe_subscription_id: str | None = None,
    gifted_by_phone: str | None = None,
    auto_renew: bool = True,
) -> Subscription:
    now = datetime.now(UTC)
    start = period_start or now

    if not period_end:
        if plan_type in ("monthly", "group_monthly"):
            period_end = start + timedelta(days=30)
        else:
            period_end = start + timedelta(days=365)

    phone, _ = await crud_phone_number.get_or_create(db, number=phone_number)

    gifted_by_phone_id = None
    if gifted_by_phone:
        gifted_phone, _ = await crud_phone_number.get_or_create(
            db, number=gifted_by_phone
        )
        gifted_by_phone_id = gifted_phone.id

    sub = Subscription(
        user_id=user_id,
        phone_number_id=phone.id,
        plan_type=plan_type,
        status=SubscriptionStatus.ACTIVE if user_id else SubscriptionStatus.PENDING,
        source=source,
        current_period_start=start,
        current_period_end=period_end,
        stripe_checkout_session_id=stripe_checkout_session_id,
        stripe_subscription_id=stripe_subscription_id,
        gifted_by_phone_id=gifted_by_phone_id,
        auto_renew=auto_renew,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def ensure_comp_access(
    db: AsyncSession, phone_number: str, user_id: UUID
) -> None:
    """Idempotently grant lifetime complimentary access to an admin-managed
    account (an enabled AccountGrant) so it can reach subscription-gated
    check-in (iOS has no purchase CTA, and the free trial is a single session).
    No-op if the account already holds an active COMP subscription. Caller
    confirms an enabled grant exists first (crud_account_grant)."""
    now = datetime.now(UTC)
    existing = await db.execute(
        select(Subscription).where(
            and_(
                Subscription.user_id == user_id,
                Subscription.source == SubscriptionSource.COMP.value,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.current_period_end > now,
            )
        )
    )
    if existing.scalar_one_or_none():
        return

    await create_subscription(
        db,
        phone_number=phone_number,
        plan_type=PlanType.ANNUAL.value,
        source=SubscriptionSource.COMP.value,
        user_id=user_id,
        # Far-future so it never lapses (and lapse reminders never fire).
        period_end=now + timedelta(days=3650),
        auto_renew=False,
    )


async def apply_referral_credit(
    db: AsyncSession, user_id: UUID, days: int | None = None
) -> None:
    credit_days = days or settings.REFERRAL_CREDIT_DAYS
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return

    now = datetime.now(UTC)
    if user.free_credit_end and user.free_credit_end > now:
        user.free_credit_end = user.free_credit_end + timedelta(days=credit_days)
    else:
        user.free_credit_end = now + timedelta(days=credit_days)

    await db.commit()


async def resolve_pending_gifts(
    db: AsyncSession, phone_number: str, user_id: UUID
) -> None:
    result = await db.execute(
        select(Subscription)
        .join(PhoneNumber, Subscription.phone_number_id == PhoneNumber.id)
        .where(
            and_(
                PhoneNumber.number == phone_number,
                Subscription.user_id.is_(None),
                Subscription.status == SubscriptionStatus.PENDING,
            )
        )
    )
    pending_subs = result.scalars().all()

    for sub in pending_subs:
        sub.user_id = user_id
        sub.status = SubscriptionStatus.ACTIVE

    if pending_subs:
        await db.commit()


async def is_promotion_active(db: AsyncSession) -> bool:
    now = datetime.now(UTC)
    result = await db.execute(
        select(Promotion).where(
            and_(
                Promotion.is_active.is_(True),
                Promotion.start_date <= now,
                Promotion.end_date >= now,
            )
        )
    )
    return result.scalar_one_or_none() is not None


async def get_referral_stats(db: AsyncSession, user_id: UUID) -> dict:
    total = await db.execute(
        select(func.count())
        .select_from(Referral)
        .where(Referral.referrer_user_id == user_id)
    )
    completed = await db.execute(
        select(func.count())
        .select_from(Referral)
        .where(
            and_(
                Referral.referrer_user_id == user_id,
                Referral.status == ReferralStatus.COMPLETED,
            )
        )
    )
    return {
        "total_referrals": total.scalar() or 0,
        "completed_referrals": completed.scalar() or 0,
    }
