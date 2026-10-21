"""The delivery reconciler — the worker phases that drive notification_deliveries
rows to a terminal state.

  send_due_deliveries    — claim each due row (crud.claim — an atomic,
                           TTL-guarded compare-and-swap, committed before any
                           provider I/O) so calling this from more than one
                           place at once (the tick vs. an inline
                           request-path dispatch) can't double-send, then send
                           it on its channel and record the provider result
                           (accepted → sent; a push then awaits its Expo
                           receipt — every push kind is receipt-tracked; dead
                           token / opted-out → refused; else backoff).
  poll_expo_receipts     — for sent push rows of receipt-tracked kinds, fetch the
                           real APNs/FCM outcome and confirm/refuse/re-queue.
  expire_and_escalate    — expire rows past their TTL, and (for circle-directed
                           kinds) enqueue an owner "contact unreachable" when a
                           delivery is exhausted/refused.
  derive_session_promotions — MISSED → ALERTED once ≥1 circle_alert reached, and
                           enqueue the owner's circle_alerted push.

Everything is idempotent (dedupe_key + ON CONFLICT) and commits per unit so a
provider hang can't strand earlier work. Related: crud/notification_delivery.py,
services/notification_policy.py, services/expo_notifications.py.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.crud import crud_alert, crud_circle_of_trust, crud_session
from app.crud import crud_notification_delivery as crud_nd
from app.crud.notification_delivery import DeliveryDraft
from app.models.alert import Alert, AlertStatus
from app.models.circle_of_trust import ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.models.phone_number import PhoneNumber
from app.models.session import Session
from app.models.user import User
from app.services import sms_opt_out
from app.services.expo_notifications import (
    ExpoPushNotificationService,
    clear_dead_push_tokens,
)
from app.services.notification_constants import (
    ALERT_DETAILS_SUFFIX,
    ALERT_RENUDGE_BODY,
    CIRCLE_ALERTED_BODY,
    CIRCLE_ALERTED_TITLE,
    CONTACT_UNREACHABLE_BODY,
    CONTACT_UNREACHABLE_TITLE,
)
from app.services.notification_policy import (
    POLICIES,
    make_dedupe_key,
    policy_for,
)
from app.utils.phone import format_for_display

logger = logging.getLogger("notification_outbox")

_RECEIPT_AGE = timedelta(seconds=30)

_DELIVERY_FAIL_STATES = {
    DeliveryStatus.EXHAUSTED,
    DeliveryStatus.REFUSED,
    DeliveryStatus.SUPERSEDED,
}


# ---------------------------------------------------------------------------
# Broadcast enqueue (owner + circle lifecycle notifications). Every lifecycle
# push/SMS that used to fire-and-forget now rides the outbox so a transient
# provider failure retries instead of vanishing (defect 5). Channels come from
# the per-kind policy; a push row needs a user id, an SMS row a phone id.
# ---------------------------------------------------------------------------


def build_broadcast_rows(
    kind: NotificationKind,
    *,
    scope_id: UUID | str,
    now: datetime,
    title: str | None,
    body: str,
    sms_body: str | None = None,
    data: dict | None = None,
    recipient_user_id: UUID | None = None,
    recipient_phone_id: UUID | None = None,
    session_id: UUID | None = None,
    occurrence: str | None = None,
    expires_at: datetime | None = None,
) -> list[DeliveryDraft]:
    """Build the push/SMS DeliveryDrafts for one recipient of a broadcast kind,
    honoring the kind's policy channels. Push needs a user id (token); SMS needs
    a phone id. TTL defaults to the policy's expires_after from `now`."""
    policy = policy_for(kind)
    if expires_at is None and policy.expires_after:
        expires_at = now + policy.expires_after
    rows: list[DeliveryDraft] = []
    if DeliveryChannel.PUSH in policy.channels and recipient_user_id is not None:
        rows.append(
            DeliveryDraft(
                dedupe_key=make_dedupe_key(
                    kind,
                    scope_id=scope_id,
                    channel=DeliveryChannel.PUSH,
                    recipient_user_id=recipient_user_id,
                    occurrence=occurrence,
                ),
                kind=kind,
                channel=DeliveryChannel.PUSH,
                title=title,
                body=body,
                next_attempt_at=now,
                recipient_user_id=recipient_user_id,
                session_id=session_id,
                expires_at=expires_at,
                data=data,
            )
        )
    if DeliveryChannel.SMS in policy.channels and recipient_phone_id is not None:
        rows.append(
            DeliveryDraft(
                dedupe_key=make_dedupe_key(
                    kind,
                    scope_id=scope_id,
                    channel=DeliveryChannel.SMS,
                    recipient_phone_id=recipient_phone_id,
                    occurrence=occurrence,
                ),
                kind=kind,
                channel=DeliveryChannel.SMS,
                body=sms_body if sms_body is not None else body,
                next_attempt_at=now,
                recipient_phone_id=recipient_phone_id,
                session_id=session_id,
                expires_at=expires_at,
                data=data,
            )
        )
    return rows


async def enqueue_and_send(
    db: AsyncSession, rows: list[DeliveryDraft], *, now: datetime | None = None
) -> int:
    """Enqueue broadcast rows and dispatch what's due inline (best-effort, for
    latency), committing atomically. Returns the count enqueued. The reconciler
    still owns retries — an inline send failure just leaves the row for the next
    tick. Safe to call from a request/webhook path."""
    if not rows:
        return 0
    now = now or datetime.now(UTC)
    enqueued = await crud_nd.enqueue(db, rows=rows)
    await db.commit()
    try:
        await send_due_deliveries(db, now=now)
    except Exception:
        # benign: inline send is best-effort; the tick retries and reports
        logger.warning("inline broadcast send failed", exc_info=True)
    return enqueued


async def rollup_alert_status(
    db: AsyncSession, alert_id: UUID | None, now: datetime
) -> None:
    """Keep the business Alert.status as a rollup of its delivery rows so the
    mobile/web/admin views stay accurate. Never overrides ACKNOWLEDGED/RESOLVED
    (owned by the claim/resolve paths). Any DELIVERED → DELIVERED; else any SENT
    → SENT; else all-failed → FAILED."""
    if not alert_id:
        return
    alert = await db.get(Alert, alert_id)
    if not alert or alert.status in (
        AlertStatus.ACKNOWLEDGED,
        AlertStatus.RESOLVED,
    ):
        return
    rows = list(
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.alert_id == alert_id
                )
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return
    statuses = {r.status for r in rows}
    if DeliveryStatus.DELIVERED in statuses:
        alert.status = AlertStatus.DELIVERED
        alert.delivered_at = alert.delivered_at or now
    elif DeliveryStatus.SENT in statuses:
        alert.status = AlertStatus.SENT
    elif statuses <= _DELIVERY_FAIL_STATES:
        alert.status = AlertStatus.FAILED
        alert.failed_at = alert.failed_at or now
    await db.flush()


# ---------------------------------------------------------------------------
# Recipient resolution (no lazy relationship loads under async).
# ---------------------------------------------------------------------------


async def _resolve_push_token(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    return user.expo_push_token if user else None


async def _resolve_phone(
    db: AsyncSession,
    *,
    phone_id: UUID | None,
    user_id: UUID | None,
) -> str | None:
    if phone_id:
        phone = await db.get(PhoneNumber, phone_id)
        return phone.number if phone else None
    if user_id:
        user = await db.get(User, user_id)
        if user and user.phone_number_id:
            phone = await db.get(PhoneNumber, user.phone_number_id)
            return phone.number if phone else None
    return None


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


async def _dispatch_push(
    db: AsyncSession,
    d: NotificationDelivery,
    policy,
    now: datetime,
    counts: dict[str, int],
) -> None:
    token = await _resolve_push_token(db, d.recipient_user_id)
    if not token:
        await crud_nd.mark_terminal(
            db,
            delivery=d,
            status=DeliveryStatus.REFUSED,
            error="no push token",
            now=now,
        )
        counts["refused"] += 1
        return

    try:
        result = await ExpoPushNotificationService.send_notification(
            push_tokens=[token],
            title=d.title or "",
            body=d.body,
            data=d.data or {},
            priority="high",
            category_id=(d.data or {}).get("category_id"),
        )
    except Exception as e:
        # A provider EXCEPTION (a refusal comes back as a result, not a raise):
        # report it with its stack, then record the attempt so the row backs off.
        logger.exception("push_send_raised", extra={"delivery_id": str(d.id)})
        result = {"ok_tokens": [], "dead_tokens": [], "message": str(e)}
    if token in result.get("ok_tokens", []):
        ticket_id = result.get("ticket_ids", {}).get(token)
        await crud_nd.mark_sent(
            db, delivery=d, provider="expo", provider_message_id=ticket_id, now=now
        )
        # Every push kind is receipt-tracked (policy invariant), so an
        # accepted push awaits its receipt (poll_expo_receipts).
        counts["sent"] += 1
        return

    dead = result.get("dead_tokens", [])
    if token in dead:
        await clear_dead_push_tokens(db, dead)
        await crud_nd.mark_terminal(
            db,
            delivery=d,
            status=DeliveryStatus.REFUSED,
            error="DeviceNotRegistered",
            now=now,
        )
        counts["refused"] += 1
    else:
        await crud_nd.mark_failed_with_backoff(
            db,
            delivery=d,
            backoff_seconds=policy.backoff_seconds,
            max_attempts=policy.max_attempts,
            error=result.get("message") or "push not accepted",
            now=now,
        )
        counts["failed"] += 1


async def _dispatch_sms(
    db: AsyncSession,
    d: NotificationDelivery,
    policy,
    now: datetime,
    counts: dict[str, int],
) -> None:
    phone = await _resolve_phone(
        db, phone_id=d.recipient_phone_id, user_id=d.recipient_user_id
    )
    if not phone:
        await crud_nd.mark_terminal(
            db, delivery=d, status=DeliveryStatus.REFUSED, error="no phone", now=now
        )
        counts["refused"] += 1
        return

    try:
        result = await sms_opt_out.gated_send_sms(db, phone, d.body)
    except Exception as e:
        # A transport EXCEPTION (Twilio/SNS return provider failures as results):
        # report it with its stack, then record the attempt so the row backs off.
        logger.exception("sms_send_raised", extra={"delivery_id": str(d.id)})
        await crud_nd.mark_failed_with_backoff(
            db,
            delivery=d,
            backoff_seconds=policy.backoff_seconds,
            max_attempts=policy.max_attempts,
            error=str(e),
            now=now,
        )
        counts["failed"] += 1
        return
    if result.success:
        await crud_nd.mark_sent(
            db,
            delivery=d,
            provider=result.provider.value if result.provider else "twilio",
            provider_message_id=result.message_id,
            now=now,
        )
        # SMS delivery is confirmed later by the provider webhook (mark_delivered).
        counts["sent"] += 1
    elif result.error == "opted_out":
        await crud_nd.mark_terminal(
            db, delivery=d, status=DeliveryStatus.REFUSED, error="opted_out", now=now
        )
        counts["refused"] += 1
    else:
        await crud_nd.mark_failed_with_backoff(
            db,
            delivery=d,
            backoff_seconds=policy.backoff_seconds,
            max_attempts=policy.max_attempts,
            error=result.error,
            now=now,
        )
        counts["failed"] += 1


async def send_due_deliveries(
    db: AsyncSession, *, now: datetime | None = None, limit: int = 100
) -> dict[str, int]:
    """Send every due row exactly once, even though this function is called
    from more than one place concurrently (the worker tick under its advisory
    lock, AND inline from request paths — `enqueue_and_send`, `process_overdue`
    — that run outside it). `get_due`'s SKIP LOCKED select only protects rows
    while this call's own transaction is open; since each row commits on its
    own (below), a second caller's `get_due` could otherwise see the same row
    the moment this call's SELECT-holding transaction ends for an earlier row.
    So each row is claimed (crud.claim) — an atomic, TTL-guarded
    compare-and-swap — and committed BEFORE any provider I/O; a lost claim
    means another dispatcher already has the row, so this call skips it."""
    now = now or datetime.now(UTC)
    counts = {"sent": 0, "delivered": 0, "failed": 0, "refused": 0, "claim_lost": 0}
    due = await crud_nd.get_due(db, now=now, limit=limit)
    for d in due:
        # Stamp the claim with the wall clock, not `now`: the tick's `now` is
        # taken at tick start and a batch can outlive CLAIM_TTL, so a
        # `now`-stamped claim could already be stale — stealable — the moment
        # it's written. (max() keeps tests that pass a future `now` coherent.)
        won = await crud_nd.claim(
            db,
            delivery_id=d.id,
            now=now,
            claim_time=max(now, datetime.now(UTC)),
        )
        await db.commit()
        if not won:
            # Expected under concurrent dispatch (an SOS request racing the
            # worker tick, or two overlapping ticks) — not an error.
            logger.info("outbox_claim_lost", extra={"delivery_id": str(d.id)})
            counts["claim_lost"] += 1
            continue
        # `d` was loaded by get_due, possibly before another dispatcher
        # touched the row (expire_on_commit=False keeps the stale copy):
        # reload it so the transitions below build on the committed state
        # (attempt_count, claimed_at) rather than overwrite it.
        await db.refresh(d)

        policy = policy_for(d.kind)
        if d.channel == DeliveryChannel.PUSH:
            await _dispatch_push(db, d, policy, now, counts)
        else:
            await _dispatch_sms(db, d, policy, now, counts)
        await rollup_alert_status(db, d.alert_id, now)
        # Escalate the moment a circle-directed delivery ends unreachable.
        if policy.escalate_on_exhausted and d.status in (
            DeliveryStatus.EXHAUSTED,
            DeliveryStatus.REFUSED,
        ):
            await _escalate_unreachable(db, d, now)
        await db.commit()
    return counts


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

_RECEIPT_KINDS = [k for k, p in POLICIES.items() if p.track_expo_receipts]


async def poll_expo_receipts(
    db: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    now = now or datetime.now(UTC)
    counts = {"delivered": 0, "failed": 0, "refused": 0}
    rows = list(
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.status == DeliveryStatus.SENT,
                    NotificationDelivery.provider == "expo",
                    NotificationDelivery.kind.in_(_RECEIPT_KINDS),
                    NotificationDelivery.sent_at <= now - _RECEIPT_AGE,
                )
            )
        )
        .scalars()
        .all()
    )
    ticket_ids = [r.provider_message_id for r in rows if r.provider_message_id]
    if not ticket_ids:
        return counts

    result = await ExpoPushNotificationService.get_receipts(ticket_ids)
    receipts = result.get("receipts", {})
    for r in rows:
        receipt = receipts.get(r.provider_message_id)
        if not receipt:
            continue  # no receipt yet — keep waiting (or expiry eventually reaps)
        if receipt["ok"]:
            await crud_nd.mark_delivered(db, delivery=r, now=now)
            counts["delivered"] += 1
        elif receipt["dead"]:
            token = await _resolve_push_token(db, r.recipient_user_id)
            if token:
                await clear_dead_push_tokens(db, [token])
            await crud_nd.mark_terminal(
                db,
                delivery=r,
                status=DeliveryStatus.REFUSED,
                error="DeviceNotRegistered",
                now=now,
            )
            counts["refused"] += 1
        else:
            policy = policy_for(r.kind)
            await crud_nd.mark_failed_with_backoff(
                db,
                delivery=r,
                backoff_seconds=policy.backoff_seconds,
                max_attempts=policy.max_attempts,
                error=receipt.get("error"),
                now=now,
            )
            counts["failed"] += 1
        await rollup_alert_status(db, r.alert_id, now)
    await db.commit()
    return counts


# ---------------------------------------------------------------------------
# Escalation + expiry
# ---------------------------------------------------------------------------


async def _escalate_unreachable(
    db: AsyncSession, d: NotificationDelivery, now: datetime
) -> None:
    """Enqueue an owner 'contact unreachable' for an exhausted/refused circle
    delivery. Idempotent per (session, member) via the dedupe key. {name}
    resolves from the circle membership's display_name for the refused row's
    phone id — the owner's OWN label for this contact, not the raw phone
    number or the contact's account name alone — falling back to "a Circle
    member" when the membership can't be found (or the delivery was somehow
    keyed by user id instead, which circle-alert rows never are in
    practice — session_tasks.py always sets a phone id for these)."""
    if not d.session_id:
        return
    session = await db.get(Session, d.session_id)
    if not session:
        return
    owner_id = session.user_id

    if d.recipient_phone_id:
        member_ref = f"p:{d.recipient_phone_id}"
        # One lookup per escalation (unique on (user_id, phone id); the
        # contact_user relationship is joined-loaded, so display_name costs
        # no further query).
        member = await crud_circle_of_trust.get_relationship(
            db, user_id=owner_id, contact_phone_number_id=d.recipient_phone_id
        )
        name = (member.display_name if member else None) or "a Circle member"
    else:
        member_ref = f"u:{d.recipient_user_id}"
        user = (
            await db.get(User, d.recipient_user_id) if d.recipient_user_id else None
        )
        name = (user.full_name if user and user.full_name else None) or "a Circle member"

    title = CONTACT_UNREACHABLE_TITLE
    body = CONTACT_UNREACHABLE_BODY.format(name=name)
    sms_body = f"{title}\n{body}"
    policy = policy_for(NotificationKind.CONTACT_UNREACHABLE)
    rows = [
        DeliveryDraft(
            dedupe_key=make_dedupe_key(
                NotificationKind.CONTACT_UNREACHABLE,
                scope_id=session.id,
                channel=ch,
                recipient_user_id=owner_id,
                occurrence=member_ref,
            ),
            kind=NotificationKind.CONTACT_UNREACHABLE,
            channel=ch,
            title=title if ch == DeliveryChannel.PUSH else None,
            body=body if ch == DeliveryChannel.PUSH else sms_body,
            next_attempt_at=now,
            recipient_user_id=owner_id,
            session_id=session.id,
            expires_at=(now + policy.expires_after) if policy.expires_after else None,
            data={"type": "contact_unreachable", "session_id": str(session.id)},
        )
        for ch in policy.channels
    ]
    await crud_nd.enqueue(db, rows=rows)
    logger.error(
        "notification_delivery_exhausted_escalated",
        extra={"session_id": str(session.id), "owner_user_id": str(owner_id)},
    )


async def expire_and_escalate(
    db: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    """Reap overdue rows to EXHAUSTED (PENDING/FAILED past `expires_at`, plus
    a SENT push of a receipt-tracked kind — `_RECEIPT_KINDS` — whose Expo
    receipt never arrived within RECEIPT_WINDOW; a SENT SMS is never reaped
    here) and escalate any that are circle-directed. `_RECEIPT_KINDS` is
    derived from notification_policy.POLICIES (`track_expo_receipts=True`,
    which every kind with a PUSH channel sets), not a hand list, and none of
    them has `escalate_on_exhausted=True` today, so a reaped SENT push never
    actually escalates in practice — the loop below still covers it the same
    way it covers everything else, so that stays true by construction, not
    by a special case, if a future push kind opts in."""
    now = now or datetime.now(UTC)
    expired = await crud_nd.expire_overdue(
        db, now=now, push_receipt_kinds=_RECEIPT_KINDS
    )
    escalated = 0
    for d in expired:
        if policy_for(d.kind).escalate_on_exhausted:
            await _escalate_unreachable(db, d, now)
            escalated += 1
    await db.commit()
    return {"expired": len(expired), "escalated": escalated}


# ---------------------------------------------------------------------------
# Session status derivation
# ---------------------------------------------------------------------------


async def _enqueue_renudge(
    db: AsyncSession, session: Session, *, now: datetime
) -> None:
    """Enqueue a circle re-nudge for every active circle member, fired
    ALERT_REMINDER_DELAY_MINUTES from now. Superseded on claim / mark-safe, so
    it only ever reaches a circle that stayed silent. SMS only (owner decision:
    Circle members are notified by SMS only). The member's existing alert id
    rides in the SMS Details link (public alert page) but is NOT
    the delivery's alert_id FK — a re-nudge is a fresh notification, so it stays
    out of the original alert's rollup and per-alert delivery queries.
    Idempotent via the CIRCLE_RENUDGE dedupe key."""
    members = await crud_circle_of_trust.get_user_contacts(
        db, user_id=session.user_id, status=ContactStatus.ACTIVE
    )
    if not members:
        return

    alerts = await crud_alert.get_session_alerts(db, session_id=session.id)
    alert_by_user = {a.sent_to_user_id: a for a in alerts if a.sent_to_user_id}
    alert_by_phone = {a.sent_to_phone_id: a for a in alerts if a.sent_to_phone_id}

    name = session.user.full_name
    phone = format_for_display(session.user.phone_number)
    body = ALERT_RENUDGE_BODY.format(name=name, phone=phone)
    fire_at = now + timedelta(minutes=settings.ALERT_REMINDER_DELAY_MINUTES)
    policy = policy_for(NotificationKind.CIRCLE_RENUDGE)
    expires = fire_at + policy.expires_after if policy.expires_after else None

    for member in members:
        muid = member.contact_user.id if member.contact_user else None
        # An app member's alert is keyed by user id; a phone-only member's by phone.
        alert = (
            alert_by_user.get(muid)
            if muid
            else alert_by_phone.get(member.contact_phone_number_id)
        )
        alert_id = alert.id if alert else None
        data = {
            "alert_id": str(alert_id) if alert_id else None,
            "user_id": str(session.user_id),
            "type": "alert_triggered",
        }
        sms_body = body
        if alert_id:
            sms_body += ALERT_DETAILS_SUFFIX.format(
                link=f"{settings.SHORT_DOMAIN}/a/{alert_id}"
            )
        await crud_nd.enqueue(
            db,
            rows=[
                DeliveryDraft(
                    dedupe_key=make_dedupe_key(
                        NotificationKind.CIRCLE_RENUDGE,
                        scope_id=session.id,
                        channel=DeliveryChannel.SMS,
                        recipient_phone_id=member.contact_phone_number_id,
                    ),
                    kind=NotificationKind.CIRCLE_RENUDGE,
                    channel=DeliveryChannel.SMS,
                    body=sms_body,
                    next_attempt_at=fire_at,
                    recipient_phone_id=member.contact_phone_number_id,
                    session_id=session.id,
                    expires_at=expires,
                    data=data,
                )
            ],
        )


async def derive_session_promotions(
    db: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    """MISSED → ALERTED once at least one circle_alert has been reached, and
    enqueue the owner's 'circle_alerted' push + the circle re-nudge. Idempotent."""
    now = now or datetime.now(UTC)
    missed = list(
        (
            await db.execute(
                select(Session)
                .where(Session.status == "missed")
                .options(joinedload(Session.user).joinedload(User.phone))
            )
        )
        .scalars()
        .all()
    )
    promoted = 0
    for s in missed:
        reached = await crud_nd.count_reached_for_session(
            db, session_id=s.id, kind=NotificationKind.CIRCLE_ALERT
        )
        if reached < 1:
            continue
        flipped = await crud_session.mark_as_alerted(db, session_id=s.id)
        if flipped is None:
            continue  # already alerted (race)
        policy = policy_for(NotificationKind.CIRCLE_ALERTED)
        await crud_nd.enqueue(
            db,
            rows=[
                DeliveryDraft(
                    dedupe_key=make_dedupe_key(
                        NotificationKind.CIRCLE_ALERTED,
                        scope_id=s.id,
                        channel=DeliveryChannel.PUSH,
                        recipient_user_id=s.user_id,
                    ),
                    kind=NotificationKind.CIRCLE_ALERTED,
                    channel=DeliveryChannel.PUSH,
                    title=CIRCLE_ALERTED_TITLE,
                    body=CIRCLE_ALERTED_BODY,
                    next_attempt_at=now,
                    recipient_user_id=s.user_id,
                    session_id=s.id,
                    expires_at=(now + policy.expires_after)
                    if policy.expires_after
                    else None,
                    data={"type": "circle_alerted", "session_id": str(s.id)},
                )
            ],
        )
        await _enqueue_renudge(db, s, now=now)
        promoted += 1
    await db.commit()
    return {"promoted": promoted}


async def is_circle_unreachable(db: AsyncSession, session: Session) -> bool:
    """Server truth for "we couldn't reach anyone" on the owner's poll.

    True only when the session is stuck MISSED and every CIRCLE_ALERT delivery
    is terminally undeliverable (REFUSED/EXHAUSTED — nothing reached, nothing
    still retrying), or none were ever created because the circle emptied
    before dispatch. Fail-safe False in every ambiguous state: rows still
    in flight, the brief window between the worker claiming the session and
    enqueueing deliveries (rows absent but members exist), or ALERTED (someone
    was reached). Without this flag the owner's surfaces would say "Notifying
    your circle…" forever while nobody is coming.
    """
    if str(session.status) != "missed":
        return False
    if await crud_nd.has_pending_or_reached(
        db, session_id=session.id, kind=NotificationKind.CIRCLE_ALERT
    ):
        return False
    if await crud_nd.has_rows_for_session(
        db, session_id=session.id, kind=NotificationKind.CIRCLE_ALERT
    ):
        return True  # rows exist and all are terminally undeliverable
    members = await crud_circle_of_trust.get_user_contacts(
        db, user_id=session.user_id, status=ContactStatus.ACTIVE
    )
    return not members
