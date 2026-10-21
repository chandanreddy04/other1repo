"""CRUD for the notification_deliveries outbox.

`enqueue` is idempotent (ON CONFLICT DO NOTHING on dedupe_key) and does NOT
commit by default — it rides the caller's transaction so the delivery row is
written atomically with the state change that owes it. The reconciler
(services/notification_outbox.py) uses `get_due` + the state transitions here to
drive every row to a terminal state.

`claim` is the compare-and-swap that lets `send_due_deliveries` be called from
more than one place (the worker tick under its advisory lock, AND inline from
request paths like `enqueue_and_send`/`process_overdue` that run outside it)
without double-sending: it flips `claimed_at` from NULL/stale to the claim time
via one `UPDATE ... WHERE id = :id AND <still due> AND (claimed_at IS NULL OR
claimed_at < :stale)`, so only one caller's UPDATE affects a row even if both
callers' `get_due` selected it in the same instant — and a caller holding a
stale copy of a row another dispatcher already sent (claimed_at cleared again)
can't re-claim it, because the row is no longer due. `get_due` excludes rows
with a fresh claim (younger than CLAIM_TTL) so a claimed-but-unfinished row
isn't handed to a second dispatcher; a crashed dispatcher's claim ages out and
the row becomes claimable again. Every terminal/backoff transition below clears `claimed_at`.

Related: models/notification_delivery.py, services/notification_policy.py.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_delivery import (
    TERMINAL_STATUSES,
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)


@dataclass
class DeliveryDraft:
    dedupe_key: str
    kind: NotificationKind
    channel: DeliveryChannel
    body: str
    next_attempt_at: datetime
    recipient_user_id: uuid.UUID | None = None
    recipient_phone_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    alert_id: uuid.UUID | None = None
    title: str | None = None
    data: dict | None = None
    expires_at: datetime | None = None


# Statuses that expire_overdue's PENDING/FAILED sweep reaps to EXHAUSTED.
# SENT is excluded from THIS list: the provider accepted it (the recipient's
# device/carrier took it), so a plain expires_at pass must NOT expire it into
# a false "contact unreachable" escalation. A SENT **push** whose Expo
# receipt never arrives is instead reaped by the separate sent-push sweep
# below (`push_receipt_kinds`) — see `expire_overdue`. A SENT **SMS** is never
# expired by either sweep: Twilio may deliver hours later, and the delivery
# webhook (not a timeout) is the source of truth for it.
_EXPIRABLE_STATUSES = (
    DeliveryStatus.PENDING,
    DeliveryStatus.FAILED,
)

# How long a claim is honored before it's treated as abandoned (a dispatcher
# that claimed a row and then crashed/hung before reaching a terminal/backoff
# update) and the row becomes claimable again. Well above any single dispatch
# call's expected duration (a provider round-trip), well below the shortest
# backoff (30s) times the number of retries a stuck row would otherwise miss.
CLAIM_TTL = timedelta(minutes=5)

# How long a SENT push can go without an Expo delivery receipt before
# expire_overdue reaps it as EXHAUSTED ("no receipt"). Expo receipts are
# normally available within ~15 min of the push being accepted and Expo
# keeps them for ~24 h, so 30 min is a policy choice (a wide margin over the
# normal latency), not an Expo limit. The boundary is inclusive: a row whose
# `sent_at` is exactly RECEIPT_WINDOW old is reaped. A receipt that turns up
# after the reap is ignored — poll_expo_receipts only selects SENT rows, so
# the EXHAUSTED row is never re-transitioned. Only applies
# to a push channel row of a receipt-tracked kind (`push_receipt_kinds`) —
# never SMS (see `_EXPIRABLE_STATUSES` above).
RECEIPT_WINDOW = timedelta(minutes=30)


def _due_clause(now: datetime):
    """The 'due for dispatch' predicate shared by get_due and claim: a
    pending/failed row whose backoff has elapsed and which hasn't expired.
    claim re-asserts it in its UPDATE's WHERE so a row another dispatcher
    already finished (SENT/terminal — which clears claimed_at) or pushed into
    backoff can't be re-claimed from a stale in-memory copy."""
    return and_(
        NotificationDelivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.FAILED]),
        NotificationDelivery.next_attempt_at <= now,
        (NotificationDelivery.expires_at.is_(None))
        | (NotificationDelivery.expires_at > now),
    )


def _unclaimed_clause(stale_before: datetime):
    """No claim, or only an abandoned one (older than CLAIM_TTL)."""
    return (NotificationDelivery.claimed_at.is_(None)) | (
        NotificationDelivery.claimed_at < stale_before
    )


class CRUDNotificationDelivery:
    async def enqueue(
        self,
        db: AsyncSession,
        *,
        rows: list[DeliveryDraft],
        commit: bool = False,
    ) -> int:
        """Insert delivery rows, skipping any whose dedupe_key already exists.
        Returns the number actually inserted. Rides the caller's transaction
        unless commit=True."""
        if not rows:
            return 0
        now = datetime.now(UTC)
        values = [
            {
                "id": uuid.uuid4(),
                "dedupe_key": r.dedupe_key,
                "kind": r.kind,
                "channel": r.channel,
                "recipient_user_id": r.recipient_user_id,
                "recipient_phone_id": r.recipient_phone_id,
                "session_id": r.session_id,
                "alert_id": r.alert_id,
                "status": DeliveryStatus.PENDING,
                "attempt_count": 0,
                "next_attempt_at": r.next_attempt_at,
                "expires_at": r.expires_at,
                "title": r.title,
                "body": r.body,
                "data": r.data,
                "created_at": now,
            }
            for r in rows
        ]
        stmt = (
            pg_insert(NotificationDelivery)
            .values(values)
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
        )
        result = await db.execute(stmt)
        if commit:
            await db.commit()
        return result.rowcount or 0

    async def get_due(
        self, db: AsyncSession, *, now: datetime, limit: int = 100
    ) -> list[NotificationDelivery]:
        """Pending/failed rows whose backoff has elapsed and which haven't
        expired or been claimed by another (not-yet-stale) dispatcher,
        oldest-due first. SKIP LOCKED so concurrent ticks never contend on the
        same row (belt-and-braces alongside the claim step and the advisory
        lock)."""
        stmt = (
            select(NotificationDelivery)
            .where(_due_clause(now), _unclaimed_clause(now - CLAIM_TTL))
            .order_by(NotificationDelivery.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def claim(
        self,
        db: AsyncSession,
        *,
        delivery_id: uuid.UUID,
        now: datetime,
        claim_time: datetime | None = None,
    ) -> bool:
        """Atomically claim a row before dispatching it: one UPDATE whose WHERE
        requires the row to still be due (`_due_clause(now)`, the same
        predicate as get_due) AND unclaimed or only stale-claimed (CLAIM_TTL
        before `claim_time`). Under READ COMMITTED a concurrent claimer's
        UPDATE blocks on the row lock and then re-evaluates this WHERE against
        the committed row, so exactly one wins. Returns True iff this call won.

        `now` is the caller's due-clock (the one it passed get_due);
        `claim_time` (default `now`) is the timestamp stamped into claimed_at
        and the staleness baseline — the dispatcher passes the wall clock so a
        long batch started with an old `now` can't stamp an already-stale
        claim. The caller must commit right away, before any provider I/O, so
        the claim is visible to a concurrent dispatcher's `get_due`."""
        claim_time = claim_time or now
        stmt = (
            update(NotificationDelivery)
            .where(
                NotificationDelivery.id == delivery_id,
                _due_clause(now),
                _unclaimed_clause(claim_time - CLAIM_TTL),
            )
            .values(claimed_at=claim_time)
            .execution_options(synchronize_session=False)
        )
        result = await db.execute(stmt)
        return result.rowcount == 1

    async def mark_sent(
        self,
        db: AsyncSession,
        *,
        delivery: NotificationDelivery,
        provider: str,
        provider_message_id: str | None,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        delivery.status = DeliveryStatus.SENT
        delivery.provider = provider
        delivery.provider_message_id = provider_message_id
        delivery.sent_at = now
        delivery.attempt_count += 1
        delivery.claimed_at = None
        await db.flush()

    async def mark_delivered(
        self,
        db: AsyncSession,
        *,
        delivery: NotificationDelivery,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = now
        delivery.terminal_at = now
        delivery.claimed_at = None
        await db.flush()

    async def mark_failed_with_backoff(
        self,
        db: AsyncSession,
        *,
        delivery: NotificationDelivery,
        backoff_seconds: tuple[int, ...],
        max_attempts: int,
        error: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Record a failed attempt: schedule the next per the backoff schedule,
        or flip to EXHAUSTED once max_attempts is reached."""
        now = now or datetime.now(UTC)
        delivery.attempt_count += 1
        delivery.last_error = error
        if delivery.attempt_count >= max_attempts:
            delivery.status = DeliveryStatus.EXHAUSTED
            delivery.terminal_at = now
        else:
            delivery.status = DeliveryStatus.FAILED
            idx = min(delivery.attempt_count - 1, len(backoff_seconds) - 1)
            delivery.next_attempt_at = now + timedelta(
                seconds=backoff_seconds[idx]
            )
        delivery.claimed_at = None
        await db.flush()

    async def mark_terminal(
        self,
        db: AsyncSession,
        *,
        delivery: NotificationDelivery,
        status: DeliveryStatus,
        error: str | None = None,
        now: datetime | None = None,
    ) -> None:
        """Set a terminal status directly (REFUSED / SUPERSEDED)."""
        now = now or datetime.now(UTC)
        delivery.status = status
        if error is not None:
            delivery.last_error = error
        delivery.terminal_at = now
        delivery.claimed_at = None
        await db.flush()

    async def expire_overdue(
        self,
        db: AsyncSession,
        *,
        now: datetime,
        push_receipt_kinds: Sequence[NotificationKind] = (),
    ) -> list[NotificationDelivery]:
        """Flip non-terminal rows past their expires_at to EXHAUSTED, and
        separately reap a SENT **push** whose Expo receipt never arrived.
        Returns the rows so the caller can run escalation (as with any other
        exhausted row — today no push kind has `escalate_on_exhausted=True`,
        so this is a no-op in practice; documented, not hardcoded).

        The first sweep (PENDING/FAILED past `expires_at`) skips a row
        another dispatcher has freshly claimed (it's mid-send; its own
        transition decides the outcome, and expiring it underneath would
        enqueue a false 'contact unreachable' for a message that then goes
        out) and, via SKIP LOCKED, a row a dispatcher's get_due/claim holds
        locked; a lock taken here in turn makes a racing claim re-check the
        row and lose once it's EXHAUSTED. An abandoned claim ages out after
        CLAIM_TTL and the row is reaped then.

        The second sweep only runs when the caller passes `push_receipt_kinds`
        (the kinds whose policy sets `track_expo_receipts=True` —
        `notification_outbox._RECEIPT_KINDS`; defaults to `()` so a caller
        that doesn't pass it, including existing tests, gets exactly the
        original PENDING/FAILED-only behaviour). It reaps a row that is still
        SENT, on the PUSH channel, of one of those kinds, whose `sent_at` is
        older than RECEIPT_WINDOW, to EXHAUSTED with `last_error="no
        receipt"`. `poll_expo_receipts` can't race this: every row it
        processes leaves SENT for DELIVERED, REFUSED, or FAILED-with-backoff
        — it never leaves a row it touched as SENT with an old `sent_at`, so
        there's no double transition; and since it only selects SENT rows, a
        receipt that arrives after this sweep reaped the row is ignored (the
        row stays EXHAUSTED). A SENT **SMS** row is never touched by
        either sweep — Twilio may deliver hours later, and the delivery
        webhook, not a timeout, is the source of truth for it."""
        result = await db.execute(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status.in_(_EXPIRABLE_STATUSES),
                NotificationDelivery.expires_at.is_not(None),
                NotificationDelivery.expires_at <= now,
                _unclaimed_clause(now - CLAIM_TTL),
            )
            .with_for_update(skip_locked=True)
            # The tick's session keeps ORM objects across commits
            # (expire_on_commit=False): overwrite any stale in-memory copy so
            # the claimed_at=None below is a real change and gets flushed.
            .execution_options(populate_existing=True)
        )
        rows = list(result.scalars().all())
        for row in rows:
            row.status = DeliveryStatus.EXHAUSTED
            row.terminal_at = now
            row.claimed_at = None

        if push_receipt_kinds:
            sent_result = await db.execute(
                select(NotificationDelivery)
                .where(
                    NotificationDelivery.status == DeliveryStatus.SENT,
                    NotificationDelivery.channel == DeliveryChannel.PUSH,
                    NotificationDelivery.kind.in_(list(push_receipt_kinds)),
                    NotificationDelivery.sent_at.is_not(None),
                    NotificationDelivery.sent_at <= now - RECEIPT_WINDOW,
                    _unclaimed_clause(now - CLAIM_TTL),
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            sent_rows = list(sent_result.scalars().all())
            for row in sent_rows:
                row.status = DeliveryStatus.EXHAUSTED
                row.terminal_at = now
                row.claimed_at = None
                row.last_error = "no receipt"
            rows.extend(sent_rows)

        if rows:
            await db.flush()
        return rows

    async def supersede(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        kind: NotificationKind,
        now: datetime | None = None,
    ) -> int:
        """Mark all non-terminal rows for a session+kind SUPERSEDED (e.g. a claim
        cancels pending re-nudges). Returns the count."""
        now = now or datetime.now(UTC)
        result = await db.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.session_id == session_id,
                NotificationDelivery.kind == kind,
                NotificationDelivery.status.not_in(list(TERMINAL_STATUSES)),
            )
            .values(status=DeliveryStatus.SUPERSEDED, terminal_at=now, claimed_at=None)
        )
        return result.rowcount or 0

    async def get_by_provider_message_id(
        self, db: AsyncSession, provider_message_id: str
    ) -> NotificationDelivery | None:
        result = await db.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.provider_message_id == provider_message_id
            )
        )
        return result.scalar_one_or_none()

    async def count_reached_for_session(
        self, db: AsyncSession, *, session_id: uuid.UUID, kind: NotificationKind
    ) -> int:
        """How many of a session's deliveries of a kind reached the recipient
        (sent or delivered) — feeds MISSED→ALERTED derivation."""
        result = await db.execute(
            select(func.count())
            .select_from(NotificationDelivery)
            .where(
                NotificationDelivery.session_id == session_id,
                NotificationDelivery.kind == kind,
                NotificationDelivery.status.in_(
                    [DeliveryStatus.SENT, DeliveryStatus.DELIVERED]
                ),
            )
        )
        return result.scalar_one()

    async def has_pending_or_reached(
        self, db: AsyncSession, *, session_id: uuid.UUID, kind: NotificationKind
    ) -> bool:
        """True while any delivery of this kind is still in flight (PENDING /
        FAILED-retrying) or already reached the recipient (SENT/DELIVERED).
        False only when every row is terminally undeliverable (REFUSED /
        EXHAUSTED / SUPERSEDED) or no rows exist — feeds circle_unreachable."""
        result = await db.execute(
            select(NotificationDelivery.id)
            .where(
                NotificationDelivery.session_id == session_id,
                NotificationDelivery.kind == kind,
                NotificationDelivery.status.in_(
                    [
                        DeliveryStatus.PENDING,
                        DeliveryStatus.SENT,
                        DeliveryStatus.DELIVERED,
                        DeliveryStatus.FAILED,
                    ]
                ),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def has_rows_for_session(
        self, db: AsyncSession, *, session_id: uuid.UUID, kind: NotificationKind
    ) -> bool:
        """True when any delivery row of this kind exists for the session,
        regardless of status."""
        result = await db.execute(
            select(NotificationDelivery.id)
            .where(
                NotificationDelivery.session_id == session_id,
                NotificationDelivery.kind == kind,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


crud_notification_delivery = CRUDNotificationDelivery()
