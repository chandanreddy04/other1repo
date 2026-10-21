"""Testable business logic for the session notification pipeline.

Core processing functions called by worker_tick.py each minute.
SOS sessions are immediately overdue — process_overdue handles both
SOS and CHECKIN types via the same codepath.

Related: worker_tick.py (caller), crud/session.py (atomic claims),
         services/notification_constants.py (string literals),
         .claude/rules/domain-sessions-alerts.md
"""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.crud import (
    crud_alert,
    crud_circle_of_trust,
    crud_session,
    crud_session_reminder,
)
from app.crud import (
    crud_notification_delivery as crud_nd,
)
from app.crud.notification_delivery import DeliveryDraft
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import ContactStatus
from app.models.notification_delivery import DeliveryChannel, NotificationKind
from app.models.session import Session, SessionStatus, SessionType
from app.models.session_update import SessionUpdate
from app.models.user import User
from app.services.blob_storage import BlobStorageService
from app.services.notification_constants import (
    ALERT_BODY_BATTERY_SUFFIX,
    ALERT_DESTINATION_SUFFIX,
    ALERT_DETAILS_SUFFIX,
    ALERT_MISSED_BODY,
    ALERT_MISSED_BODY_NO_TIME,
    ALERT_SOS_BODY,
    SESSION_DEADLINE_BODY,
    SESSION_DEADLINE_TITLE,
)
from app.services.notification_policy import make_dedupe_key, policy_for
from app.utils.phone import format_for_display

logger = logging.getLogger(__name__)

# Battery rides along in alert copy only when critically low — at 3% it's a
# safety signal ("their phone is about to die, don't rely on reaching them");
# at 60% it's noise. Owner decision 2026-07-02 (docs/flow-review.md §4.3).
LOW_BATTERY_ALERT_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_local_time(dt_utc: datetime, tz_offset_minutes: int | None) -> str | None:
    """Render a stored-UTC datetime as a local clock time ("10:30 PM").

    Uses the client UTC offset captured at session creation. Returns None
    when no offset was captured — callers must fall back to time-free copy
    rather than showing a UTC clock time.
    """
    if tz_offset_minutes is None:
        return None
    local = dt_utc + timedelta(minutes=tz_offset_minutes)
    # %I is zero-padded; strip the leading zero portably (%-I is glibc-only).
    return local.strftime("%I:%M %p").lstrip("0")


def _format_local_datetime(
    dt_utc: datetime, tz_offset_minutes: int | None
) -> str | None:
    """Render a stored-UTC datetime as a local date + clock time
    ("Sep 23, 12:51 AM") — for lists spanning days, where a bare clock time
    is ambiguous. Same offset source and None fallback as _format_local_time
    (never a UTC clock time)."""
    if tz_offset_minutes is None:
        return None
    local = dt_utc + timedelta(minutes=tz_offset_minutes)
    # %-d / %-I are glibc-only; build the unpadded day and hour portably.
    clock = local.strftime("%I:%M %p").lstrip("0")
    return f"{local.strftime('%b')} {local.day}, {clock}"


def _build_alert_content(session: Session) -> tuple[AlertType, str]:
    """Build (alert_type, body) for a circle alert.

    SOS and missed check-in get distinct bodies: an SOS is a deliberate act
    (3s hold, ~zero false positives) while a missed check-in is a passive
    inference — recipients must be able to tell them apart. The body is
    shared by push, SMS, and the Alert record — there's no per-type push
    TITLE any more (the SOS/missed titles were deleted 2026-09-27):
    circle alerts are SMS-only (owner decision 2026-09-22), so a title was
    never sent. Destination rides along when available; battery only when
    critically low (see LOW_BATTERY_ALERT_THRESHOLD). Both are
    permission-dependent, so the copy degrades gracefully. Copy:
    docs/flow-review.md §4.3 (B2).
    """
    name = session.user.full_name
    phone = format_for_display(session.user.phone_number)

    if session.session_type == SessionType.SOS.value:
        alert_type = AlertType.PANIC
        body = ALERT_SOS_BODY.format(name=name, phone=phone)
    else:
        alert_type = AlertType.MISSED_SESSION
        local_time = _format_local_time(
            session.expected_return_time, session.tz_offset_minutes
        )
        if local_time:
            body = ALERT_MISSED_BODY.format(name=name, time=local_time, phone=phone)
        else:
            body = ALERT_MISSED_BODY_NO_TIME.format(name=name, phone=phone)

    if session.destination:
        body += ALERT_DESTINATION_SUFFIX.format(destination=session.destination)
    # column_property attached in models/__init__.py — invisible to mypy,
    # hence getattr instead of direct attribute access.
    battery_level: float | None = getattr(session, "last_battery_level", None)
    if battery_level is not None and battery_level < LOW_BATTERY_ALERT_THRESHOLD:
        body += ALERT_BODY_BATTERY_SUFFIX.format(level=round(battery_level * 100))
    return alert_type, body


# ---------------------------------------------------------------------------
# Core processing — called by cron worker
# ---------------------------------------------------------------------------


async def _enqueue_circle_alerts(db: AsyncSession, session: Session) -> int:
    """Create Alert rows + enqueue circle_alert SMS deliveries (owner decision:
    Circle members are notified by SMS only, regardless of app account) for
    members who don't yet have an alert. Idempotent: skipping already-alerted
    members and the delivery dedupe keys make re-running (retry / new members
    joining mid-incident) safe. The reconciler owns sending + retry; this only
    enqueues. Commits atomically."""
    circle_members = await crud_circle_of_trust.get_user_contacts(
        db, user_id=session.user_id, status=ContactStatus.ACTIVE
    )
    if not circle_members:
        return 0

    existing = await crud_alert.get_session_alerts(db, session_id=session.id)
    alerted_user_ids = {a.sent_to_user_id for a in existing if a.sent_to_user_id}
    alerted_phone_ids = {a.sent_to_phone_id for a in existing if a.sent_to_phone_id}

    alert_type, body = _build_alert_content(session)
    now = datetime.now(UTC)
    policy = policy_for(NotificationKind.CIRCLE_ALERT)
    expires = now + policy.expires_after if policy.expires_after else None

    enqueued = 0
    for member in circle_members:
        muid = member.contact_user.id if member.contact_user else None
        if muid and muid in alerted_user_ids:
            continue
        if not muid and member.contact_phone_number_id in alerted_phone_ids:
            continue

        # Flush-only alert creation so the alert + its deliveries commit together.
        alert = Alert(
            session_id=session.id,
            sent_to_user_id=muid,
            sent_to_phone_id=None if muid else member.contact_phone_number_id,
            alert_type=alert_type,
            message=body,
            status=AlertStatus.SENT,
            sent_at=now,
        )
        db.add(alert)
        await db.flush()

        data = {
            "alert_id": str(alert.id),
            "user_id": str(session.user_id),
            "type": "alert_triggered",
        }
        # The alert id doubles as the access token to the public alert page.
        sms_body = body + ALERT_DETAILS_SUFFIX.format(
            link=f"{settings.SHORT_DOMAIN}/a/{alert.id}"
        )

        enqueued += await crud_nd.enqueue(
            db,
            rows=[
                DeliveryDraft(
                    dedupe_key=make_dedupe_key(
                        NotificationKind.CIRCLE_ALERT,
                        scope_id=session.id,
                        channel=DeliveryChannel.SMS,
                        recipient_phone_id=member.contact_phone_number_id,
                    ),
                    kind=NotificationKind.CIRCLE_ALERT,
                    channel=DeliveryChannel.SMS,
                    body=sms_body,
                    next_attempt_at=now,
                    recipient_phone_id=member.contact_phone_number_id,
                    session_id=session.id,
                    alert_id=alert.id,
                    expires_at=expires,
                    data=data,
                )
            ],
        )

    await db.commit()
    return enqueued


async def process_overdue(db: AsyncSession, session_id: str | UUID) -> dict:
    """Atomically claim an overdue session and enqueue circle alerts.

    Uses claim_for_processing as the coordination gate. The circle alerts are
    enqueued to the outbox and dispatched inline for latency (SOS can't wait a
    tick); the reconciler owns retries + the MISSED→ALERTED promotion.
    """
    from app.services.notification_helpers import send_session_expired_notification
    from app.services.notification_outbox import (
        derive_session_promotions,
        send_due_deliveries,
    )

    sid = UUID(str(session_id))

    claimed = await crud_session.claim_for_processing(db, session_id=sid)
    if claimed is None:
        return {"alerts_sent": False}

    result = await db.execute(
        select(Session).options(selectinload(Session.user)).where(Session.id == sid)
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"alerts_sent": False}

    if session.session_type == SessionType.CHECKIN.value:
        # Enqueue-only; committed below alongside the circle alerts (or on its
        # own if the owner has no circle) so it survives even an empty circle.
        await send_session_expired_notification(db, session.user, session)

    enqueued = await _enqueue_circle_alerts(db, session)
    # _enqueue_circle_alerts commits when it enqueues; commit here too so the
    # owner's session-expired notification lands even when there's no circle.
    await db.commit()

    # Dispatch inline (SOS/overdue latency), then promote if a member was reached.
    await send_due_deliveries(db)
    if enqueued == 0:
        return {"alerts_sent": False}
    await derive_session_promotions(db)
    reached = await crud_nd.count_reached_for_session(
        db, session_id=sid, kind=NotificationKind.CIRCLE_ALERT
    )
    return {"alerts_sent": reached > 0}


async def process_missed_session(db: AsyncSession, session_id: UUID) -> dict:
    """Top up circle alerts for a MISSED session — enqueue for members who don't
    yet have an alert (e.g. joined mid-incident), dispatch inline, and let the
    reconciler promote MISSED→ALERTED once a member is reached. Idempotent."""
    from app.services.notification_outbox import (
        derive_session_promotions,
        send_due_deliveries,
    )

    result = await db.execute(
        select(Session)
        .options(selectinload(Session.user))
        .where(Session.id == session_id, Session.status == SessionStatus.MISSED.value)
    )
    session = result.scalar_one_or_none()
    if not session:
        return {"alerts_sent": False}

    await _enqueue_circle_alerts(db, session)
    await send_due_deliveries(db)
    await derive_session_promotions(db)
    reached = await crud_nd.count_reached_for_session(
        db, session_id=session_id, kind=NotificationKind.CIRCLE_ALERT
    )
    return {"alerts_sent": reached > 0}


async def process_pending_reminders(db: AsyncSession) -> int:
    """Send all pending owner reminders and mark them sent.

    Returns the number of reminders processed.
    """
    reminders = await crud_session_reminder.get_pending(db)
    sent = 0
    for reminder in reminders:
        ok = await send_owner_reminder(
            db, str(reminder.session_id), reminder.minutes_before
        )
        if ok:
            await crud_session_reminder.mark_sent(db, reminder_id=reminder.id)
        sent += 1
    return sent


async def schedule_reminders_for_session(
    db: AsyncSession, session_id: UUID, deadline: datetime
) -> int:
    """Create SessionReminder rows for a session deadline.

    Called from session creation and extension endpoints.
    Returns the number of reminders created.
    """
    # An extension reschedules — supersede any reminder deliveries already
    # enqueued for the old deadline so a stale reminder can't still fire
    # (no-op on creation, where none exist yet).
    await crud_nd.supersede(
        db, session_id=session_id, kind=NotificationKind.OWNER_REMINDER
    )
    await crud_nd.supersede(
        db, session_id=session_id, kind=NotificationKind.OWNER_DEADLINE
    )
    rows = await crud_session_reminder.create_reminders_for_session(
        db, session_id=session_id, deadline=deadline
    )
    return len(rows)


# ---------------------------------------------------------------------------
# Owner reminders and cleanup
# ---------------------------------------------------------------------------


async def send_owner_reminder(
    db: AsyncSession, session_id: str, minutes_before: int
) -> bool:
    """Enqueue the at-deadline owner SMS (owner_deadline).

    Owner decision 2026-07-18: every reminder PUSH (30/10/5/0) is a
    client-scheduled local notification now — the device's own clock fires
    them in dead zones and backend outages, which server pushes can't reach.
    The server's one remaining reminder duty is the minutes == 0 SMS: the
    channel the client can't send, and it reaches a phone with notifications
    denied/DND. Pre-deadline rows are no longer scheduled; legacy rows still
    in the table are consumed as no-ops (True marks them done without
    enqueueing anything)."""
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.user))
        .where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session or session.status != SessionStatus.ACTIVE.value:
        return False

    if minutes_before > 0:
        # Legacy pre-deadline schedule row from before the client-side ladder
        # shipped — the device covers this rung locally; consume, send nothing.
        return True

    kind = NotificationKind.OWNER_DEADLINE
    title = SESSION_DEADLINE_TITLE
    body = SESSION_DEADLINE_BODY.format(grace_minutes=settings.GRACE_PERIOD_MINUTES)

    now = datetime.now(UTC)
    # Stale once the deadline+grace has passed (the session is overdue by then).
    expires = session.expected_return_time + timedelta(
        minutes=settings.GRACE_PERIOD_MINUTES
    )
    # Occurrence keys on the deadline + rung so an extension mints new keys (old
    # ones get superseded) and the ladder rungs stay distinct.
    occurrence = f"{session.expected_return_time.isoformat()}:{minutes_before}"
    data = {
        "session_id": str(session.id),
        "type": "session_expiring",
        "minutes_remaining": minutes_before,
    }
    rows = [
        # SMS only — the at-deadline push is the client's local T-0 rung.
        DeliveryDraft(
            dedupe_key=make_dedupe_key(
                kind,
                scope_id=session.id,
                channel=DeliveryChannel.SMS,
                recipient_user_id=session.user_id,
                occurrence=occurrence,
            ),
            kind=kind,
            channel=DeliveryChannel.SMS,
            body=f"{title}\n{body}",
            next_attempt_at=now,
            recipient_user_id=session.user_id,
            session_id=session.id,
            expires_at=expires,
            data=data,
        )
    ]
    await crud_nd.enqueue(db, rows=rows, commit=True)
    return True


async def complete_session_with_all_clear(
    db: AsyncSession, session: Session, owner: User
) -> Session:
    """The ONE mark-safe path: session → COMPLETED, pending owner reminders
    deleted; if the session had escalated (MISSED/ALERTED), outstanding
    alerts are resolved, queued circle deliveries superseded, and the
    all-clear broadcast to the active circle. Shared by the owner's mobile
    "I'm Safe" endpoint and the admin mark-safe-on-their-behalf action so
    the two completion paths can't drift."""
    from app.services.notification_helpers import send_all_clear_to_circle

    was_missed = session.status in {
        SessionStatus.MISSED.value,
        SessionStatus.ALERTED.value,
    }

    session = await crud_session.complete_session(db, session=session)
    await crud_session_reminder.delete_for_session(db, session_id=session.id)

    if was_missed:
        await crud_alert.resolve_session_alerts(db, session_id=session.id)
        # Owner is safe — stop any pending circle alerts / re-nudges queued.
        await crud_nd.supersede(
            db, session_id=session.id, kind=NotificationKind.CIRCLE_ALERT
        )
        await crud_nd.supersede(
            db, session_id=session.id, kind=NotificationKind.CIRCLE_RENUDGE
        )
        await db.commit()

        circle_members = await crud_circle_of_trust.get_user_contacts(
            db, user_id=owner.id, status=ContactStatus.ACTIVE
        )
        if circle_members:
            await send_all_clear_to_circle(db, circle_members, owner, session)

    return session


async def purge_session_data(
    db: AsyncSession, session: Session, blob_service: BlobStorageService
) -> dict[str, int]:
    """Delete ONE session's captured data (outfit photo, location trail). Shared by the retention cleanup and the admin
    "purge data now" action so the two paths can't drift. Does not commit.
    """
    counts = {
        "photos_deleted": 0,
        "locations_deleted": 0,
    }

    if session.outfit_photo_url:
        # Storage key = URL path (S3 virtual-hosted URLs:
        # https://{bucket}.s3.{region}.amazonaws.com/{key}).
        key = urlparse(session.outfit_photo_url).path.lstrip("/")
        if await blob_service.delete_file(key):
            session.outfit_photo_url = None
            session.outfit_photo_uploaded_at = None
            counts["photos_deleted"] += 1

    loc_result = await db.execute(
        select(SessionUpdate).where(SessionUpdate.session_id == session.id)
    )
    session_updates = loc_result.scalars().all()
    for loc in session_updates:
        await db.delete(loc)
    counts["locations_deleted"] += len(session_updates)

    # Record when deletion ACTUALLY happened — purge_after can't say this
    # (the admin early-purge never touches the schedule). Surfaces render
    # "deleted on {purged_at}" from this.
    session.purged_at = datetime.now(UTC)

    return counts


async def cleanup_expired_data(db: AsyncSession) -> dict:
    """Purge photos and location data from terminal sessions past retention,
    plus expired sponsorship sign-in tokens.

    Data survives SESSION_DATA_RETENTION_DAYS after completion (extensible
    by the owner from History via purge_after — flow-review E2/3.10). NULL
    purge_after = legacy row from the purge-immediately era: already
    purgeable.

    DELIBERATE CARVE-OUT (owner decision 2026-07-19): sessions never marked
    safe (stuck MISSED/ALERTED) are NOT auto-purged — in the worst case the
    trail/photos are evidence for an investigation, and the one person who
    could extend retention is the person who is missing. Their public page
    goes neutral after ALERT_PAGE_MAX_AGE_DAYS; data disposal is a human
    decision via the admin session actions. Pinned by
    tests/test_never_resolved_retention.py.

    Sponsorship sign-in tokens (app/models/sponsorship_sign_in_token.py)
    are small and short-lived (10 min TTL) — an unrelated table, purged
    here rather than in its own hourly job since this function already is
    the hourly-cleanup entry point (worker_tick.py calls it on the hour).
    """
    from app.crud.sponsorship_sign_in_token import crud_sponsorship_sign_in_token
    from app.services.notification_helpers import send_data_deleted_notification

    terminal_statuses = [SessionStatus.COMPLETED.value, SessionStatus.CANCELLED.value]

    result = await db.execute(
        select(Session)
        .options(selectinload(Session.user))
        .where(
            Session.status.in_(terminal_statuses),
            (Session.purge_after.is_(None))
            | (Session.purge_after <= datetime.now(UTC)),
        )
    )
    expired_sessions = result.scalars().all()

    blob_service = BlobStorageService()
    photos_deleted = 0
    locations_deleted = 0
    notified_users: set[UUID] = set()

    for session in expired_sessions:
        counts = await purge_session_data(db, session, blob_service)
        photos_deleted += counts["photos_deleted"]
        locations_deleted += counts["locations_deleted"]
        had_data = any(counts.values())

        if had_data and session.user_id not in notified_users:
            notified_users.add(session.user_id)
            await send_data_deleted_notification(db, session.user, session)

    await db.commit()

    if photos_deleted or locations_deleted:
        logger.info(
            "Session data cleanup: %d outfit photos, %d location records purged",
            photos_deleted,
            locations_deleted,
        )

    sign_in_tokens_purged = await crud_sponsorship_sign_in_token.purge_expired(db)
    if sign_in_tokens_purged:
        logger.info(
            "Sponsorship sign-in token cleanup: %d expired tokens purged",
            sign_in_tokens_purged,
        )

    return {
        "photos_deleted": photos_deleted,
        "locations_deleted": locations_deleted,
        "sign_in_tokens_purged": sign_in_tokens_purged,
    }
