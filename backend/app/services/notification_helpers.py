"""Notification dispatch helpers for session lifecycle events.

Every lifecycle notification here enqueues notification_deliveries rows that the
reconciler (services/notification_outbox.py) dispatches and retries — owner
session-expired, all-clear to the circle, data-deleted, the STOP-cascade owner
notifications, and (since 2026-09-27) the two account-holder STOP pushes.

Related: services/notification_outbox.py, services/session_tasks.py,
         services/notification_constants.py
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification_delivery import DeliveryDraft
from app.crud.notification_delivery import crud_notification_delivery as crud_nd
from app.models.circle_of_trust import CircleOfTrustMember
from app.models.notification_delivery import NotificationKind
from app.models.session import Session
from app.models.user import User
from app.services.notification_constants import (
    ACCOUNT_HOLDER_STOPPED_BODY,
    ACCOUNT_HOLDER_STOPPED_TITLE,
    ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED_BODY,
    ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED_TITLE,
    ALL_CLEAR_SMS,
    CIRCLE_EMPTIED_BODY,
    CIRCLE_EMPTIED_MID_SESSION_BODY,
    CIRCLE_EMPTIED_MID_SESSION_TITLE,
    CIRCLE_EMPTIED_TITLE,
    CIRCLE_WELCOME_SMS,
    CONTACT_LEFT_BODY,
    CONTACT_LEFT_TITLE,
    CONTACT_OPTED_OUT_BODY,
    CONTACT_OPTED_OUT_TITLE,
    DATA_DELETED_BODY,
    DATA_DELETED_BODY_NO_TIME,
    DATA_DELETED_TITLE,
    SESSION_EXPIRED_BODY,
    SESSION_EXPIRED_TITLE,
    SOFT_STOP_GATE_ACCOUNT_AND_CONTACT,
    SOFT_STOP_GATE_ACCOUNT_AND_CONTACT_SINGLE,
    SOFT_STOP_GATE_ACCOUNT_ONLY,
    SOFT_STOP_GATE_GENERIC,
    SOFT_STOP_GATE_MULTI_OWNER,
    SOFT_STOP_GATE_SINGLE_OWNER,
)
from app.services.notification_outbox import (
    build_broadcast_rows,
    enqueue_and_send,
)
from app.services.session_tasks import _format_local_time
from app.services.sms import sms_service
from app.services.sms_opt_out import OwnerImpact, SenderProfile

logger = logging.getLogger(__name__)


async def send_session_expired_notification(
    db: AsyncSession, user: User, session: Session
) -> int:
    """Enqueue the owner's 'you missed your check-in' push + SMS backup.

    Enqueue-only — rides the caller's transaction (process_overdue commits and
    dispatches inline via the reconciler). SMS is a backup for a critical
    notification, so a denied-notifications phone still hears about it.
    """
    rows = build_broadcast_rows(
        NotificationKind.SESSION_EXPIRED_OWNER,
        scope_id=session.id,
        now=datetime.now(UTC),
        title=SESSION_EXPIRED_TITLE,
        body=SESSION_EXPIRED_BODY,
        sms_body=f"{SESSION_EXPIRED_TITLE}\n{SESSION_EXPIRED_BODY}",
        data={"session_id": str(session.id), "type": "session_expired"},
        recipient_user_id=user.id,
        recipient_phone_id=user.phone_number_id,
        session_id=session.id,
    )
    return await crud_nd.enqueue(db, rows=rows)


async def send_all_clear_to_circle(
    db: AsyncSession,
    circle_members: list[CircleOfTrustMember],
    user: User,
    session: Session,
) -> int:
    """Notify circle members that the user has marked themselves safe.

    Enqueues SMS per member (owner decision: Circle members are notified by
    SMS only) and dispatches inline (mark-safe is a request path — the circle
    should hear promptly); the reconciler retries a transient failure instead
    of dropping it (defect 5).
    """
    now = datetime.now(UTC)
    # ALL_CLEAR is SMS-only (channels=(SMS,)) — there's no push to carry a
    # separate title, so the SMS body IS the single merged line.
    body = ALL_CLEAR_SMS.format(name=user.full_name)
    data = {
        "session_id": str(session.id),
        "user_id": str(user.id),
        "type": "all_clear",
    }
    rows = []
    for m in circle_members:
        rows.extend(
            build_broadcast_rows(
                NotificationKind.ALL_CLEAR,
                scope_id=session.id,
                now=now,
                title=None,
                body=body,
                data=data,
                recipient_phone_id=m.contact_phone_number_id,
                session_id=session.id,
            )
        )
    return await enqueue_and_send(db, rows, now=now)


def _format_started_at(session: Session) -> str | None:
    """Render session.created_at as a local "Sep 22 · 9:40 PM" timestamp for
    the data-deleted push, or None when tz_offset_minutes wasn't captured —
    the caller then sends the time-free DATA_DELETED_BODY_NO_TIME, since the
    only timestamp left would be UTC and a UTC clock time is never rendered.
    Reuses session_tasks._format_local_time for the clock portion rather
    than hand-rolling a second offset calculation."""
    offset = session.tz_offset_minutes
    if offset is None:
        return None
    local_dt = session.created_at + timedelta(minutes=offset)
    clock = _format_local_time(session.created_at, offset)
    return f"{local_dt.strftime('%b')} {local_dt.day} · {clock}"


def _data_deleted_body(session: Session) -> str:
    started_at = _format_started_at(session)
    if started_at is None:
        return DATA_DELETED_BODY_NO_TIME
    return DATA_DELETED_BODY.format(started_at=started_at)


async def send_data_deleted_notification(
    db: AsyncSession, user: User, session: Session
) -> int:
    """Enqueue the owner's 'your session data was cleaned up' push.

    Enqueue-only — rides the purge transaction; the reconciler dispatches it.
    Push-only (informational; the owner has the app).
    """
    rows = build_broadcast_rows(
        NotificationKind.DATA_DELETED,
        scope_id=session.id,
        now=datetime.now(UTC),
        title=DATA_DELETED_TITLE,
        body=_data_deleted_body(session),
        data={"session_id": str(session.id), "type": "data_deleted"},
        recipient_user_id=user.id,
        session_id=session.id,
    )
    return await crud_nd.enqueue(db, rows=rows)


async def send_circle_welcome_sms(
    accepter: User, inviter: User
) -> bool:
    """Send one-time confirmation SMS to a new circle member.

    Establishes the SMS sender number so future alerts land in a
    recognized thread. Returns True if sent, False on failure.
    """
    inviter_name = inviter.full_name or "your contact"
    body = CIRCLE_WELCOME_SMS.format(inviter_name=inviter_name)

    if not accepter.phone_number:
        return False

    result = await sms_service.send_sms(to_phone=accepter.phone_number, message=body)
    return result.success


def _cascade_kind(impact: OwnerImpact, reason: str = "opted_out") -> NotificationKind:
    """Which owner-directed cascade notification fits this impact.

    `reason` distinguishes the "others remain" case: a STOP-cascade opt-out
    is CONTACT_OPTED_OUT, a web leave (`circle_invitations.leave_circle`) is
    CONTACT_LEFT — a separate outbox kind so the audit trail tells the two
    triggers apart. The emptied-circle kinds are shared by both reasons.
    """
    if impact.has_active_session and impact.remaining_active_count == 0:
        return NotificationKind.CIRCLE_EMPTIED_MID_SESSION
    if impact.remaining_active_count == 0:
        return NotificationKind.CIRCLE_EMPTIED
    if reason == "left":
        return NotificationKind.CONTACT_LEFT
    return NotificationKind.CONTACT_OPTED_OUT


def _cascade_occurrence(impact: OwnerImpact) -> str:
    """Dedupe occurrence shared by all four cascade kinds (CONTACT_OPTED_OUT,
    CONTACT_LEFT, CIRCLE_EMPTIED, CIRCLE_EMPTIED_MID_SESSION): the membership
    id plus the moment its status last changed, not the contact's display
    name.

    A name-based occurrence would collide across two different memberships
    that happen to share a display name (two contacts nicknamed "Mom", or a
    re-added contact reusing a departed one's nickname) — one's notification
    would silently suppress the other's forever, since the dedupe constraint
    is global and permanent. Membership id alone fixes that, but a leave ->
    re-invite -> leave cycle reuses the SAME row (`revive_to_pending` revives
    it in place), so a bare membership id would still suppress the second
    leave's notification. Folding in `status_changed_at`
    (`CircleOfTrustMember.updated_at`, bumped by `onupdate` on every flip —
    soft_set_status, revive_to_pending, accept_invitation) gives each flip of
    that row its own occurrence.

    Both fields are required on `OwnerImpact`, so there is no fallback (a
    bare-id or name fallback would silently re-open the collisions above).
    The timestamp is normalised to UTC so the key doesn't depend on which
    tz the driver handed back."""
    changed_at = impact.status_changed_at.astimezone(UTC).isoformat()
    return f"{impact.membership_id}:{changed_at}"


def _cascade_rows(
    impact: OwnerImpact, now: datetime, reason: str = "opted_out"
) -> list[DeliveryDraft]:
    """Build the delivery rows for one owner's cascade notification. Most kinds
    are push-only (owner has the app); the mid-session case adds an SMS backup
    (per policy) because the owner may be in a vulnerable moment and needs to
    know SOS / overdue won't fan out even if notifications are off."""
    kind = _cascade_kind(impact, reason)
    name = impact.contact_name
    occurrence = _cascade_occurrence(impact)
    if kind is NotificationKind.CIRCLE_EMPTIED_MID_SESSION:
        title = CIRCLE_EMPTIED_MID_SESSION_TITLE
        body = CIRCLE_EMPTIED_MID_SESSION_BODY.format(name=name)
        data = {
            "type": "circle_emptied_mid_session",
            "contact_name": name,
            "session_id": str(impact.active_session_id)
            if impact.active_session_id
            else None,
        }
    elif kind is NotificationKind.CIRCLE_EMPTIED:
        title = CIRCLE_EMPTIED_TITLE
        body = CIRCLE_EMPTIED_BODY.format(name=name)
        data = {"type": "circle_emptied", "contact_name": name}
    elif kind is NotificationKind.CONTACT_LEFT:
        title = CONTACT_LEFT_TITLE
        body = CONTACT_LEFT_BODY.format(name=name)
        data = {"type": "contact_left", "contact_name": name}
    else:
        title = CONTACT_OPTED_OUT_TITLE
        body = CONTACT_OPTED_OUT_BODY.format(name=name)
        data = {"type": "contact_opted_out", "contact_name": name}
    return build_broadcast_rows(
        kind,
        scope_id=impact.owner.id,
        now=now,
        title=title,
        body=body,
        sms_body=f"{title}\n{body}",
        data=data,
        recipient_user_id=impact.owner.id,
        recipient_phone_id=impact.owner.phone_number_id,
        session_id=impact.active_session_id,
        occurrence=occurrence,
    )


async def send_account_holder_unsubscribed(db: AsyncSession, user: User) -> int:
    """Enqueue (and dispatch inline) the push telling a Made It Home user
    that THEIR OWN phone just opted out — not a contact's. STOP turns off
    OTP and all our SMS to them; they keep push and the app while logged
    in, but they've effectively cancelled the service's reach to them. We
    tell them so they don't discover it later when sign-in stops working.

    Push-only — SMS would be blocked at the opt-out gate anyway. Routed
    through the outbox (owner decision: every push auditable) instead of
    a direct `send_notification` call: a user with no push token now gets
    an auditable REFUSED "no push token" row instead of a silent early
    return, and a dead token is cleared by the reconciler
    (`notification_outbox._dispatch_push`), not here.

    Occurrence is the opt-out timestamp (`user.phone.sms_opted_out_at`,
    eagerly loaded via `User.phone`, `lazy="joined"`) so a second STOP
    after an intervening START (which clears the timestamp) notifies
    again instead of deduping against the earlier STOP.
    """
    now = datetime.now(UTC)
    occurrence = (
        user.phone.sms_opted_out_at.astimezone(UTC).isoformat()
        if user.phone and user.phone.sms_opted_out_at
        else None
    )
    rows = build_broadcast_rows(
        NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED,
        scope_id=user.id,
        now=now,
        title=ACCOUNT_HOLDER_STOPPED_TITLE,
        body=ACCOUNT_HOLDER_STOPPED_BODY,
        data={"type": "account_holder_unsubscribed"},
        recipient_user_id=user.id,
        occurrence=occurrence,
    )
    return await enqueue_and_send(db, rows, now=now)


async def send_account_holder_subscription_cancelled(
    db: AsyncSession, user: User, grace_days: int, *, subscription_id: UUID
) -> int:
    """Enqueue (and dispatch inline) the push sent grace_days after the
    user texted STOP if they haven't responded — confirms we've set
    their subscription to cancel at the next billing date.

    Push-only, routed through the outbox (owner decision: every push
    auditable) instead of a direct `send_notification` call: a user with
    no push token now gets an auditable REFUSED "no push token" row
    instead of a silent early return.

    Occurrence is the cancelled subscription's id — "once per cancelled
    sub" — so re-processing the same cancellation never re-notifies,
    while a later, different subscription being cancelled for the same
    user gets its own send.
    """
    now = datetime.now(UTC)
    rows = build_broadcast_rows(
        NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED,
        scope_id=user.id,
        now=now,
        title=ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED_TITLE,
        body=ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED_BODY.format(
            grace_days=grace_days
        ),
        data={"type": "account_holder_subscription_cancelled"},
        recipient_user_id=user.id,
        occurrence=str(subscription_id),
    )
    return await enqueue_and_send(db, rows, now=now)


async def fan_out_cascade_notifications(
    db: AsyncSession,
    impacts: list[OwnerImpact],
    *,
    reason: str = "opted_out",
) -> None:
    """Enqueue the right owner-directed cascade notification for each impact.

    `reason` is `"opted_out"` for the SMS STOP cascade
    (`sms_opt_out.cascade_circle_removal`) or `"left"` for the web leave path
    (`circle_invitations.leave_circle`) — see `_cascade_kind` for how it
    picks CONTACT_OPTED_OUT vs. CONTACT_LEFT. The emptied-circle kinds are
    unaffected by `reason`.

    Building rows is cheap and synchronous; enqueue_and_send does ONE commit +
    inline dispatch for the whole batch (the inbound webhook must respond within
    ~Twilio's timeout, and a phone in many circles must not serialize). The
    reconciler owns retries + dead-token cleanup (Expo DeviceNotRegistered), so
    a transient failure no longer silently drops the notification (defect 5).
    Idempotent: a Twilio webhook retry re-derives the same impacts and the
    dedupe key skips already-enqueued rows.
    """
    if not impacts:
        return
    now = datetime.now(UTC)
    rows = [row for impact in impacts for row in _cascade_rows(impact, now, reason)]
    await enqueue_and_send(db, rows, now=now)


def render_soft_stop_gate(profile: SenderProfile) -> str:
    """Pick the 1c case (A-E) per copy doc and render the SMS body.

    Cases:
      A. Single owner, no account → names the owner (owner_names[0])
      B. Multi-owner, no account → multi-owner template (just count)
      C. Account, no circles → account-only template
      D. Account + circles → names the owner at count 1, count-only at 2+
      E. Neither → generic template

    Owner-approved 2026-09-27: the owner's first name IS interpolated in
    cases A and D-at-count-1 (SenderProfile.owner_names, populated only in
    the single-owner shape) — naming who they'd be leaving behind makes the
    stakes concrete instead of a vague "someone".
    """
    if profile.has_account and profile.owner_count == 1:
        return SOFT_STOP_GATE_ACCOUNT_AND_CONTACT_SINGLE.format(
            name=profile.owner_names[0]
        )
    if profile.has_account and profile.owner_count > 1:
        return SOFT_STOP_GATE_ACCOUNT_AND_CONTACT.format(count=profile.owner_count)
    if profile.has_account:
        return SOFT_STOP_GATE_ACCOUNT_ONLY
    if profile.owner_count == 1:
        return SOFT_STOP_GATE_SINGLE_OWNER.format(name=profile.owner_names[0])
    if profile.owner_count >= 1:
        return SOFT_STOP_GATE_MULTI_OWNER.format(count=profile.owner_count)
    return SOFT_STOP_GATE_GENERIC
