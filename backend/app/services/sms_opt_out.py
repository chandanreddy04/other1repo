"""SMS opt-out state engine.

Single source of truth for: is this phone opted out, recording STOP/START
events, cascading the cancellation to Circle of Trust memberships, and the
soft-stop intent gate.

Outbound senders consult `is_opted_out` before dispatch. The inbound
Twilio webhook consults `soft_stop_intent` to decide between the
hard-STOP path and the soft-stop confirmation gate.

Related: api/v1/endpoints/webhooks.py (inbound), services/sms.py (gate),
api/v1/endpoints/auth.py (OTP gate), services/notification_helpers.py
(owner-side push fanout).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.crud.session import NON_TERMINAL_STATUSES
from app.models.alert import SMSProvider
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.phone_number import PhoneNumber
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.services.sms import SMSResult, sms_service
from app.utils.phone import format_to_e164

# Twilio-protected opt-out keywords. Twilio's Advanced Opt-Out auto-replies
# with our static 1b confirmation and marks the number opted-out on their
# side; we mirror that state in our DB and cascade circle memberships.
PROTECTED_STOP_KEYWORDS = frozenset(
    {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
)
# Twilio-protected re-subscribe keywords.
PROTECTED_START_KEYWORDS = frozenset({"START", "UNSTOP", "YES"})

# Phrases that signal opt-out intent but are NOT in Twilio's protected
# keyword set. These reach our webhook unhandled, so we send a personalized
# confirmation gate (1c) before letting them lose their emergency-contact
# status.
_SOFT_STOP_PHRASES = (
    "please stop",
    "stop texting",
    "remove me",
    "leave me alone",
    "don't text me",
    "dont text me",
    "do not text me",
    "no more texts",
)

SOFT_STOP_COOLDOWN_HOURS = 24


@dataclass(frozen=True)
class OwnerImpact:
    """One owner's slice of a cascade — who left, what's left in their
    circle, and whether they're mid-session right now."""

    owner: User
    contact_name: str
    remaining_active_count: int
    # True when the owner has a non-terminal session (ACTIVE, MISSED or
    # ALERTED) — "mid-session" includes a live incident.
    has_active_session: bool
    # The membership row that was removed, and the moment its status last
    # changed (`CircleOfTrustMember.updated_at`, which `onupdate` bumps on
    # every flip — soft_set_status, revive_to_pending, accept_invitation,
    # and the STOP cascade / START restore's in-place status writes).
    # Used together as the dedupe occurrence for all four cascade kinds (see
    # notification_helpers._cascade_occurrence). Required, not optional: a
    # missing value would force a fallback occurrence (bare id or display
    # name) that re-opens the collisions this key exists to prevent.
    membership_id: UUID
    status_changed_at: datetime
    active_session_id: UUID | None = None


@dataclass(frozen=True)
class SenderProfile:
    """Used by the soft-stop gate to pick its 1c case (A-E)."""

    owner_names: list[str] = field(default_factory=list)
    owner_count: int = 0
    has_account: bool = False


def soft_stop_intent(body: str | None) -> bool:
    """True if `body` reads like a stop-adjacent ask without being a
    protected keyword. Case-insensitive, normalizes curly apostrophes,
    and collapses internal whitespace so a stray newline ("please\\nstop")
    doesn't let an opt-out intent slip past the matcher."""
    if not body:
        return False
    normalized = " ".join(body.lower().replace("’", "'").split())  # noqa: RUF001
    return any(phrase in normalized for phrase in _SOFT_STOP_PHRASES)


async def _get_phone(db: AsyncSession, phone: str) -> PhoneNumber | None:
    e164 = format_to_e164(phone)
    if not e164:
        return None
    result = await db.execute(select(PhoneNumber).where(PhoneNumber.number == e164))
    return result.scalar_one_or_none()


async def is_opted_out(db: AsyncSession, phone: str) -> bool:
    """Cheap pre-flight for outbound sends — true if we've recorded a STOP
    for this number and no subsequent START has cleared it."""
    pn = await _get_phone(db, phone)
    return pn is not None and pn.sms_opted_out_at is not None


async def record_opt_out(
    db: AsyncSession, phone: str, source: str = "twilio_webhook"
) -> PhoneNumber | None:
    """Stamp `sms_opted_out_at` on the phone row. Idempotent — re-running
    after a STOP that was already recorded leaves the original timestamp
    alone so we don't reset the audit trail."""
    pn = await _get_phone(db, phone)
    if pn is None:
        return None
    if pn.sms_opted_out_at is None:
        pn.sms_opted_out_at = datetime.now(UTC)
        pn.sms_opt_out_source = source
        await db.commit()
        await db.refresh(pn)
    return pn


async def user_for_phone(db: AsyncSession, phone_id: UUID) -> User | None:
    result = await db.execute(select(User).where(User.phone_number_id == phone_id))
    return result.scalar_one_or_none()


def _contact_filter(phone_id: UUID, user: User | None):
    """SQL filter that matches memberships where the given phone is the
    contact. Every row is keyed by the contact's phone now, so a single
    predicate covers app + non-app contacts (the `user` arg is retained for
    call-site compatibility). Used by cascade + restore + profile queries."""
    return CircleOfTrustMember.contact_phone_number_id == phone_id


async def record_opt_in(db: AsyncSession, phone: str) -> PhoneNumber | None:
    """Clear opt-out state and restore any `OPTED_OUT` memberships back
    to `ACTIVE`. The membership row was preserved (not deleted) at STOP
    time precisely so we can do this in-place.

    Also undoes the subscription auto-cancellation if our worker did
    one — finds any Subscription stamped with
    `cancelled_by_sms_unsubscribe_at` for this user, calls Stripe to
    clear `cancel_at_period_end`, restores local `auto_renew=True`, and
    clears the stamps. Net effect of `STOP -> auto-cancel -> START` is
    that the user ends up in the state they were in before STOP — no
    more, no less. Cancellations the user initiated themselves via
    the Stripe portal aren't touched (no stamp).
    """
    from app.models.subscription import Subscription
    from app.services import stripe_service

    pn = await _get_phone(db, phone)
    if pn is None:
        return None
    pn.sms_opted_out_at = None
    pn.sms_opt_out_source = None

    user_with_phone = await user_for_phone(db, pn.id)

    # If the account holder texted START, clear the worker's "handled"
    # stamp so a future STOP cycle gets a fresh grace clock + re-action.
    # Without this, a user who STOPs → gets auto-cancelled → STOPs again
    # later would never trip the cancellation flow a second time.
    if user_with_phone is not None:
        user_with_phone.sms_unsubscribe_handled_at = None

        # Restore any subs we cancelled. Stripe's reactivate is
        # idempotent and the stamp prevents touching cancellations
        # the user requested themselves via the portal.
        cancelled_q = select(Subscription).where(
            Subscription.user_id == user_with_phone.id,
            Subscription.cancelled_by_sms_unsubscribe_at.is_not(None),
        )
        for sub in (await db.execute(cancelled_q)).scalars().all():
            if sub.stripe_subscription_id:
                try:
                    stripe_service.reactivate_subscription(
                        sub.stripe_subscription_id
                    )
                except Exception:
                    # Don't block START on a Stripe blip — the next
                    # subscription-updated webhook will resync, or the
                    # user can fix it from the portal. Log so ops sees it.
                    import logging

                    logging.getLogger(__name__).exception(
                        "sms_opt_in_stripe_reactivate_failed",
                        extra={
                            "stripe_subscription_id": sub.stripe_subscription_id
                        },
                    )
                    continue
            sub.auto_renew = True
            sub.cancelled_by_sms_unsubscribe_at = None

    member_q = select(CircleOfTrustMember).where(
        CircleOfTrustMember.status == ContactStatus.OPTED_OUT,
        _contact_filter(pn.id, user_with_phone),
    )
    result = await db.execute(member_q)
    for member in result.scalars().all():
        member.status = ContactStatus.ACTIVE
        member.opted_out_at = None

    await db.commit()
    await db.refresh(pn)
    return pn


async def cascade_circle_removal(
    db: AsyncSession, phone: PhoneNumber
) -> list[OwnerImpact]:
    """Flip every ACTIVE/PENDING membership where `phone` is the contact
    to OPTED_OUT, stamp the timestamp, and return one `OwnerImpact` per
    affected owner so the caller can fan out push notifications.

    Handles both join paths — `contact_phone_number_id` (non-app contacts)
    and `contact_user_id` (app contacts whose user row points at this
    phone).
    """
    user_with_phone = await user_for_phone(db, phone.id)

    affected_q = select(CircleOfTrustMember).where(
        CircleOfTrustMember.status.in_(
            [ContactStatus.ACTIVE, ContactStatus.PENDING]
        ),
        _contact_filter(phone.id, user_with_phone),
    )
    result = await db.execute(affected_q)
    affected = list(result.scalars().all())

    now = datetime.now(UTC)
    affected_by_owner: dict[UUID, CircleOfTrustMember] = {}
    for member in affected:
        member.status = ContactStatus.OPTED_OUT
        member.opted_out_at = now
        # Capture the contact name to surface in the per-owner push —
        # keep the first one encountered if an owner somehow had the
        # same phone in twice.
        affected_by_owner.setdefault(member.user_id, member)

    await db.commit()

    if not affected_by_owner:
        return []

    removals = {
        owner_id: (member, member.display_name or "Your Circle member")
        for owner_id, member in affected_by_owner.items()
    }
    return await compute_owner_impacts(db, removals)


async def compute_owner_impacts(
    db: AsyncSession,
    removals: dict[UUID, tuple[CircleOfTrustMember, str]],
) -> list[OwnerImpact]:
    """For each owner in `removals` (owner id -> (the membership row just
    removed, the display name to surface in the notification)), compute
    what's left of that owner's circle: remaining ACTIVE member count and
    the owner's current non-terminal (ACTIVE/MISSED/ALERTED) session, if
    any.

    Shared by the STOP cascade (`cascade_circle_removal`, potentially many
    owners in one inbound webhook) and the web leave path
    (`circle_invitations.leave_circle`, always exactly one owner) so "what
    happens to this owner's circle when a membership goes away" has a
    single implementation. The caller must already have flipped the
    membership's status (and committed) before calling this — it only
    reads.

    The display name fallback is the caller's job, not this function's: the
    STOP cascade falls back to "Your Circle member"; the web leave path
    falls back to "A Circle member" (its notification body already reads
    "... left your Circle of Trust", so "Your Circle member left your
    Circle of Trust" would read redundant).
    """
    if not removals:
        return []
    owner_ids = set(removals)

    # Remaining ACTIVE-circle size per owner — informs the empty-circle
    # vs. one-of-many push variants.
    counts_result = await db.execute(
        select(
            CircleOfTrustMember.user_id,
            func.count(CircleOfTrustMember.id),
        )
        .where(
            CircleOfTrustMember.user_id.in_(owner_ids),
            CircleOfTrustMember.status == ContactStatus.ACTIVE,
        )
        .group_by(CircleOfTrustMember.user_id)
    )
    remaining_by_owner = {row[0]: row[1] for row in counts_result.all()}

    # In-session owners — any session type counts (CHECKIN and SOS alike),
    # and "in session" is the non-terminal set (ACTIVE, MISSED, ALERTED —
    # `NON_TERMINAL_STATUSES`, the same set `crud_session.get_active_session`
    # uses): an owner whose session is already MISSED/ALERTED is mid-incident
    # and must get the push+SMS mid-session variant, not the push-only one.
    # Order + setdefault picks the same row get_active_session would (ACTIVE
    # first, then newest) when an owner has several non-terminal sessions.
    sessions_result = await db.execute(
        select(Session)
        .where(
            Session.user_id.in_(owner_ids),
            Session.status.in_(NON_TERMINAL_STATUSES),
        )
        .order_by(
            (Session.status != SessionStatus.ACTIVE.value).asc(),
            Session.created_at.desc(),
        )
    )
    active_session_by_owner: dict[UUID, Session] = {}
    for s in sessions_result.scalars().all():
        active_session_by_owner.setdefault(s.user_id, s)

    owners_result = await db.execute(select(User).where(User.id.in_(owner_ids)))
    owners_by_id = {u.id: u for u in owners_result.scalars().all()}

    impacts: list[OwnerImpact] = []
    for owner_id, (member, name) in removals.items():
        owner = owners_by_id.get(owner_id)
        if owner is None:
            continue
        session = active_session_by_owner.get(owner_id)
        impacts.append(
            OwnerImpact(
                owner=owner,
                contact_name=name,
                remaining_active_count=remaining_by_owner.get(owner_id, 0),
                has_active_session=session is not None,
                active_session_id=session.id if session is not None else None,
                membership_id=member.id,
                status_changed_at=member.updated_at,
            )
        )
    return impacts


async def get_sender_profile(db: AsyncSession, phone: str) -> SenderProfile:
    """Profile lookup for the soft-stop gate's case-picker.

    `owner_names` is populated only when there's exactly one owner — the
    single-owner SMS variant is the only one that drops the name in. For
    >1 owners we only need the count.
    """
    pn = await _get_phone(db, phone)
    if pn is None:
        return SenderProfile()

    user_with_phone = await user_for_phone(db, pn.id)
    has_account = user_with_phone is not None

    owners_q = (
        select(User)
        .join(
            CircleOfTrustMember,
            CircleOfTrustMember.user_id == User.id,
        )
        .where(
            CircleOfTrustMember.status.in_(
                [ContactStatus.ACTIVE, ContactStatus.PENDING]
            ),
            _contact_filter(pn.id, user_with_phone),
        )
        .distinct()
    )
    owners_result = await db.execute(owners_q)
    owners = list(owners_result.scalars().all())

    # Substitute a generic phrase if the single owner has no name on
    # file (hard-purge already nulled full_name, signup never completed)
    # so the soft-stop gate still picks the single-owner template
    # instead of falling into a "for 1 people" multi-owner grammar bug.
    # First name only (owner-approved 2026-09-27, render_soft_stop_gate
    # interpolates it as "{name}'s Circle of Trust") — split ONLY a real
    # full_name. The fallback must read possessively, so "someone" (→
    # "someone's Circle of Trust"), not a phrase like "the person who added
    # you" (→ "the person who added you's Circle of Trust").
    owner_names: list[str] = []
    if len(owners) == 1:
        full_name = owners[0].full_name
        owner_names = [full_name.split(" ")[0] if full_name else "someone"]

    return SenderProfile(
        owner_names=owner_names,
        owner_count=len(owners),
        has_account=has_account,
    )


async def should_send_soft_stop_gate(db: AsyncSession, phone: str) -> bool:
    """24h cooldown — we send at most one soft-stop confirmation per
    phone per day so a contact who keeps replying "please stop, please
    stop" isn't barraged with our gates."""
    pn = await _get_phone(db, phone)
    if pn is None:
        return True
    if pn.last_soft_stop_gate_sent_at is None:
        return True
    cutoff = datetime.now(UTC) - timedelta(hours=SOFT_STOP_COOLDOWN_HOURS)
    return pn.last_soft_stop_gate_sent_at < cutoff


async def record_soft_stop_gate_sent(db: AsyncSession, phone: str) -> None:
    """Stamp the cooldown timestamp, creating the PhoneNumber row if it
    doesn't exist yet. Without the upsert, an unknown phone that texts
    "please stop" repeatedly would never get a cooldown — the silent
    no-op leaves room for them to spam our gate SMS."""
    e164 = format_to_e164(phone)
    if not e164:
        return
    pn, _ = await crud_phone_number.get_or_create(db, number=e164)
    pn.last_soft_stop_gate_sent_at = datetime.now(UTC)
    await db.commit()


async def gated_send_sms(
    db: AsyncSession,
    to_phone: str,
    message: str,
    *,
    provider: SMSProvider | None = None,
) -> SMSResult:
    """Send-with-gate: refuse to dispatch if `to_phone` is opted out.

    Returns the same `SMSResult` shape as `sms_service.send_sms`, with
    `success=False` and `error="opted_out"` when blocked. Twilio also
    blocks opted-out numbers at the API level (error 21610), so this is
    defense-in-depth — but it avoids the round-trip, gives non-Twilio
    backends (SNS) a uniform gate, and yields a clean distinguishable
    error so callers that may want to log silently (sub-lapse, sponsor
    SMS) don't alarm on a delivery failure that's actually user-intended.

    `provider` forwards to `sms_service.send_sms` for the retry path —
    historically required to match the original sender so the delivery
    webhook resolves to the right Alert.

    Callers that have their own opt-out logic — notably the OTP gate
    which translates `opted_out` into a user-facing 400 — should call
    `is_opted_out` + `sms_service.send_sms` separately so they can
    branch on the failure before send rather than after.
    """
    if await is_opted_out(db, to_phone):
        return SMSResult(success=False, message_id=None, error="opted_out")
    return await sms_service.send_sms(to_phone, message, provider=provider)
