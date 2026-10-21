"""Subscription-end notification fan-out.

When a subscription that has dependents (group-plan members or a
sponsored beneficiary) is about to end — either because the payer
deleted their account, hit Stripe's retry budget, or manually cancelled
— the dependents need to know so they can re-subscribe before access
lapses.

This module owns:
- The user-facing SMS copy for each notification moment (T=0, T-7d,
  T-1d, T=end).
- Identification of dependents from a Subscription row.
- The dispatch fan-out (push + SMS) for one moment per subscription.

Stripe webhooks call `notify_lapse(..., Moment.T_ZERO)` immediately on
the state change; the worker tick calls it at the scheduled reminder
intervals. See docs/account-deletion-plan.md "Notification surface".

Related: app/services/notification_helpers.py (in-flight session
notifications use the same dispatch layer; subscription notifications
are separate because the audience and copy are different).
"""

import enum
import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import phonenumbers
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.group_plan import (
    GroupPlan,
    GroupPlanMember,
    GroupPlanMemberRole,
)
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.subscription import (
    PlanType,
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User
from app.services.notification_outbox import build_broadcast_rows, enqueue_and_send

logger = logging.getLogger(__name__)

SUB_SHORT_URL = f"{settings.SHORT_DOMAIN}/sub"


class Moment(enum.StrEnum):
    """When the notification fires relative to the subscription's
    `current_period_end`."""

    T_ZERO = "t_zero"  # Immediately on state change (cancel_at_period_end flipped, payment failed, etc.)
    T_MINUS_7D = "t_minus_7d"
    T_MINUS_1D = "t_minus_1d"
    T_END = "t_end"  # On natural lapse at period end


_GROUP_SMS = {
    Moment.T_ZERO: (
        "Your Group Plan from {owner_name} ends {date}. "
        "Subscribe to keep access: " + SUB_SHORT_URL
    ),
    Moment.T_MINUS_7D: (
        "Your Group Plan ends in 7 days. Subscribe now to avoid a gap: " + SUB_SHORT_URL
    ),
    Moment.T_MINUS_1D: (
        "Last day: Your Group Plan ends tomorrow. "
        "Subscribe to keep access: " + SUB_SHORT_URL
    ),
    Moment.T_END: (
        "Your Made It Home Group Plan ended today. "
        "Subscribe to continue: " + SUB_SHORT_URL
    ),
}

_SPONSOR_SMS = {
    Moment.T_ZERO: (
        "Your sponsorship from {sponsor_phone_full} ends {date}. "
        "Subscribe to keep access: " + SUB_SHORT_URL
    ),
    Moment.T_MINUS_7D: (
        "Your sponsorship ends in 7 days. Subscribe now to avoid a gap: "
        + SUB_SHORT_URL
    ),
    Moment.T_MINUS_1D: (
        "Last day: Your sponsorship ends tomorrow. "
        "Subscribe to keep access: " + SUB_SHORT_URL
    ),
    Moment.T_END: (
        "Your Made It Home sponsorship ended today. "
        "Subscribe to continue: " + SUB_SHORT_URL
    ),
}

# Per-moment push title (owner-approved 2026-09-27) — T_END reads "has ended"
# (past tense: access is already gone), every earlier moment reads "is
# ending" (a warning, not yet true).
_PUSH_TITLE = {
    Moment.T_ZERO: "Your access is ending",
    Moment.T_MINUS_7D: "Your access is ending",
    Moment.T_MINUS_1D: "Your access is ending",
    Moment.T_END: "Your access has ended",
}
_PUSH_BODY = {
    Moment.T_ZERO: "Tap to keep your Made It Home access.",
    Moment.T_MINUS_7D: "Ends in 7 days — tap to renew.",
    Moment.T_MINUS_1D: "Ends tomorrow — tap to renew.",
    Moment.T_END: "Your access ended today — tap to renew.",
}


def _format_international(e164: str) -> str:
    """Render an E.164 phone number as international display, e.g.
    `+1 (415) 555-4567` for SMS body. Falls back to the raw E.164 on
    parse failure so the message still goes out."""
    try:
        parsed = phonenumbers.parse(e164, None)
        return phonenumbers.format_number(
            parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
        )
    except phonenumbers.NumberParseException:
        # benign: an unparsable number is shown as stored
        return e164


def _format_date(d: date) -> str:
    """`Jul 6` style — matches the plan's SMS examples and the user-
    visible deletion confirmation copy."""
    return d.strftime("%b %-d")


def _is_group_sub(sub: Subscription) -> bool:
    return sub.plan_type in (
        PlanType.GROUP_MONTHLY.value,
        PlanType.GROUP_ANNUAL.value,
    )


def _is_sponsored_sub(sub: Subscription) -> bool:
    return sub.source == SubscriptionSource.STRIPE_GIFT.value


async def _group_dependents(
    db: AsyncSession, sub: Subscription
) -> tuple[list[GroupPlanMember], User | None]:
    """Active group-plan members (excluding the owner) for this sub,
    plus the owner User for substitution in the SMS body."""
    plan_result = await db.execute(
        select(GroupPlan).where(GroupPlan.subscription_id == sub.id)
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        return [], None
    members_result = await db.execute(
        select(GroupPlanMember).where(
            GroupPlanMember.group_plan_id == plan.id,
            GroupPlanMember.left_at.is_(None),
            GroupPlanMember.role != GroupPlanMemberRole.OWNER.value,
        )
    )
    return list(members_result.scalars().all()), plan.owner


async def _sponsored_dependent(db: AsyncSession, sub: Subscription) -> User | None:
    """The beneficiary user of a sponsored sub, looked up by user_id
    (subscribed user) — they're the one who loses access."""
    if sub.user_id is None:
        return None
    result = await db.execute(select(User).where(User.id == sub.user_id))
    return result.scalar_one_or_none()


def _owner_display_name(owner: User | None) -> str:
    """Returns the owner's full_name or the plan-says fallback for
    post-purge stubs (`full_name` is NULL after hard-purge)."""
    if owner is None or not owner.full_name:
        return "the plan owner"
    return owner.full_name


async def _send_to_user(
    db: AsyncSession,
    user: User,
    sms_message: str,
    push_title: str,
    push_body: str,
    *,
    scope_id: UUID,
    occurrence: str,
) -> tuple[bool, bool]:
    """Enqueue SMS + push outbox rows (kind SUBSCRIPTION_LAPSE) for a single
    dependent and dispatch inline. Returns (sms_ok, push_ok): True when the
    provider accepted that channel's send during the inline pass (the row is
    SENT/DELIVERED). False does NOT mean "not sent" — the row may still be
    PENDING (inline pass skipped it or raised) or FAILED and backing off; the
    worker's reconciler owns retries. A re-call whose rows were deduped
    reports the existing rows' status.

    Every send leaves an auditable delivery row instead of vanishing on a
    transient failure (owner decision: every push auditable). SMS still goes through the opt-out
    gate exactly as before: `notification_outbox._dispatch_sms` calls
    `sms_opt_out.gated_send_sms` for every SMS row it sends, so a dependent
    who texted STOP earlier still gets no SMS (their row lands REFUSED
    instead of raising).
    """
    now = datetime.now(UTC)
    rows = build_broadcast_rows(
        NotificationKind.SUBSCRIPTION_LAPSE,
        scope_id=scope_id,
        now=now,
        title=push_title,
        body=push_body,
        sms_body=sms_message,
        data={"type": "subscription_lapse"},
        recipient_user_id=user.id,
        recipient_phone_id=user.phone_number_id,
        occurrence=occurrence,
    )
    if not rows:
        return False, False

    await enqueue_and_send(db, rows, now=now)

    sms_ok = False
    push_ok = False
    for row in rows:
        result = await db.execute(
            select(NotificationDelivery.channel, NotificationDelivery.status).where(
                NotificationDelivery.dedupe_key == row.dedupe_key
            )
        )
        found = result.first()
        if found is None:
            continue
        channel, status = found
        ok = status in (DeliveryStatus.SENT, DeliveryStatus.DELIVERED)
        if channel == DeliveryChannel.SMS:
            sms_ok = ok
        else:
            push_ok = ok
    return sms_ok, push_ok


async def notify_lapse(
    db: AsyncSession, subscription: Subscription, moment: Moment
) -> dict[str, int]:
    """Fan out one moment's notification to every dependent of `subscription`.

    Returns a dict with `sms_sent` and `push_sent` counts for the worker-
    tick / webhook caller to log.

    Non-group, non-gifted subs have no dependents — returns zeros.
    Sponsored subs without an attached gifter phone (rare data shape;
    e.g. a sponsor row that was anonymized in a way that dropped the
    `gifted_by_phone_id`) silently skip — the SMS template needs the
    sponsor's phone to render meaningfully and we'd rather miss the
    notification than ship a template with the placeholder bare.
    Per-recipient SMS + push failures are absorbed so one failing
    recipient can't block the rest of the fan-out.

    Callers are expected to fire T_ZERO immediately on the Stripe state
    change and T_MINUS_7D / T_MINUS_1D / T_END at the right offset from
    `current_period_end`. The function does NOT enforce that — it
    renders the chosen template against `current_period_end` as-is, so
    firing T_END a few hours past midnight still reads "ended today"
    (worker tick is hourly).
    """
    period_end = subscription.current_period_end.date()
    push_title = _PUSH_TITLE[moment]
    push_body = _PUSH_BODY[moment]
    sms_sent = 0
    push_sent = 0
    # One send per moment per billing period (intended): the dedupe key is
    # (subscription, recipient, channel, moment, current_period_end), so a
    # second T_ZERO in the same period from a different trigger (cancel flip
    # then dunning-exhausted, or cancel -> reactivate -> cancel) is suppressed
    # as redundant noise, as is any re-run. A later billing period (new
    # current_period_end) gets a fresh key. Epoch seconds, not isoformat, so
    # the key can't depend on how the datetime's tzinfo renders.
    occurrence = (
        f"{moment.value}:{int(subscription.current_period_end.timestamp())}"
    )

    if _is_group_sub(subscription):
        members, owner = await _group_dependents(db, subscription)
        sms_template = _GROUP_SMS[moment]
        sms_body = sms_template.format(
            owner_name=_owner_display_name(owner),
            date=_format_date(period_end),
        )
        for member in members:
            try:
                s, p = await _send_to_user(
                    db,
                    member.user,
                    sms_body,
                    push_title,
                    push_body,
                    scope_id=subscription.id,
                    occurrence=occurrence,
                )
                sms_sent += int(s)
                push_sent += int(p)
            except Exception:
                logger.exception(
                    "sub_lapse_notify_failed",
                    extra={
                        "subscription_id": str(subscription.id),
                        "user_id": str(member.user_id),
                        "moment": moment.value,
                    },
                )

    elif _is_sponsored_sub(subscription):
        beneficiary = await _sponsored_dependent(db, subscription)
        sponsor_phone_e164 = subscription.gifted_by_phone
        if beneficiary is not None and sponsor_phone_e164:
            sms_template = _SPONSOR_SMS[moment]
            sms_body = sms_template.format(
                sponsor_phone_full=_format_international(sponsor_phone_e164),
                date=_format_date(period_end),
            )
            try:
                s, p = await _send_to_user(
                    db,
                    beneficiary,
                    sms_body,
                    push_title,
                    push_body,
                    scope_id=subscription.id,
                    occurrence=occurrence,
                )
                sms_sent += int(s)
                push_sent += int(p)
            except Exception:
                logger.exception(
                    "sub_lapse_notify_failed",
                    extra={
                        "subscription_id": str(subscription.id),
                        "user_id": str(beneficiary.id),
                        "moment": moment.value,
                    },
                )

    return {"sms_sent": sms_sent, "push_sent": push_sent}


async def process_pending_lapse_reminders(db: AsyncSession) -> dict[str, int]:
    """Worker-tick entry point — fire T-7d and T-1d reminders.

    Scans every ACTIVE subscription with auto_renew=False whose
    `current_period_end` is within the reminder window AND that hasn't
    yet been stamped for that moment. Fires `notify_lapse` and
    timestamp-stamps so the next tick can't re-fire.

    Windows are exclusive on the near side, inclusive on the far side
    and chosen so the two never overlap (a sub cancelled with <1d to
    go skips T-7d and goes straight to T-1d — the "ends in 7 days" SMS
    would be a lie):
        T-7d  fires when current_period_end is within (now + 1d, now + 7d]
        T-1d  fires when current_period_end is within (now, now + 1d]
    Idempotency is via the dedicated `lapse_reminder_*_sent_at` columns,
    so the actual window can be loose — late firing still happens once.

    Per-sub failures are caught + logged; one stuck row can't block
    the rest of the batch.
    """
    now = datetime.now(UTC)
    counts = {"reminders_sent": 0}

    # 7-day reminder — current_period_end in (now + 1d, now + 7d] AND
    # not yet sent. The lower bound is "more than 1 day away" so a sub
    # that's cancelled with <1d to go skips T-7d entirely (the "ends in
    # 7 days" copy would be a lie) and goes straight to T-1d below.
    one_day_cutoff = now + timedelta(days=1)
    seven_day_cutoff = now + timedelta(days=7)
    result_7d = await db.execute(
        select(Subscription).where(
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.auto_renew.is_(False),
            Subscription.lapse_reminder_7d_sent_at.is_(None),
            Subscription.current_period_end > one_day_cutoff,
            Subscription.current_period_end <= seven_day_cutoff,
        )
    )
    for sub in result_7d.scalars().all():
        try:
            await notify_lapse(db, sub, Moment.T_MINUS_7D)
            sub.lapse_reminder_7d_sent_at = now
            counts["reminders_sent"] += 1
        except Exception:
            logger.exception(
                "lapse_reminder_7d_failed",
                extra={"subscription_id": str(sub.id)},
            )

    # 1-day reminder — current_period_end in (now, now + 1d] AND not yet sent.
    result_1d = await db.execute(
        select(Subscription).where(
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.auto_renew.is_(False),
            Subscription.lapse_reminder_1d_sent_at.is_(None),
            Subscription.current_period_end > now,
            Subscription.current_period_end <= one_day_cutoff,
        )
    )
    for sub in result_1d.scalars().all():
        try:
            await notify_lapse(db, sub, Moment.T_MINUS_1D)
            sub.lapse_reminder_1d_sent_at = now
            counts["reminders_sent"] += 1
        except Exception:
            logger.exception(
                "lapse_reminder_1d_failed",
                extra={"subscription_id": str(sub.id)},
            )

    await db.commit()
    return counts
