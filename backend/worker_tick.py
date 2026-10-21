"""Cron worker entry-point — runs once per minute, then exits.

Processes overdue sessions, retries failed alerts, sends pending
reminders, and performs hourly cleanup. Unix cron fires a fresh
process each minute so a hang in one tick cannot block the next.

Related: services/session_tasks.py, crud/session.py, Dockerfile.worker
"""

import asyncio
import contextlib
import json
import logging
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import setup_logging
from app.crud import crud_session
from app.db.session import AsyncSessionLocal, async_engine
from app.services.notification_outbox import (
    derive_session_promotions,
    expire_and_escalate,
    poll_expo_receipts,
    send_due_deliveries,
)
from app.services.session_tasks import (
    cleanup_expired_data,
    process_overdue,
    process_pending_reminders,
)

setup_logging()
logger = logging.getLogger("worker_tick")


@contextlib.asynccontextmanager
async def _safe(
    label: str, errors: list[str], db: AsyncSession | None = None
) -> AsyncIterator[None]:
    """Run a block, logging/collecting any exception without re-raising.

    When ``db`` is provided, also roll it back on failure: a mid-transaction
    error otherwise leaves the shared session in PendingRollbackError, so
    every later phase in this tick would fail too (reminders, retries, cleanup).
    """
    try:
        yield
    except Exception as exc:
        msg = f"{label}: {exc}"
        logger.exception(msg, extra={"phase": label})
        errors.append(msg)
        if db is not None:
            try:
                await db.rollback()
            except Exception:
                logger.exception("rollback after %s failed", label)


async def tick() -> None:
    start = time.monotonic()
    now = datetime.now(UTC)
    errors: list[str] = []
    active_processed = 0
    missed_retried = 0
    reminders_sent = 0
    purges_done = 0
    lapse_reminders_sent = 0
    outbox_sent = 0
    outbox_delivered = 0
    outbox_promoted = 0
    outbox_exhausted = 0

    async with AsyncSessionLocal() as db:
        # --- Overdue ACTIVE sessions (past deadline + grace period) ---
        async with _safe("get_overdue_sessions", errors, db):
            overdue = await crud_session.get_overdue_sessions(
                db, grace_minutes=settings.GRACE_PERIOD_MINUTES
            )
            for session in overdue:
                async with _safe(f"process_overdue({session.id})", errors, db):
                    await process_overdue(db, session.id)
                    active_processed += 1

        # --- MISSED sessions (partial failure on previous tick) ---
        async with _safe("get_missed_sessions", errors, db):
            missed = await crud_session.get_missed_sessions(db)
            for session in missed:
                async with _safe(f"process_missed_session({session.id})", errors, db):
                    from app.services.session_tasks import process_missed_session

                    await process_missed_session(db, session.id)
                    missed_retried += 1

        # Alert retries are owned by the outbox reconciler (below) — the old
        # ALERTED-gated retry_failed_alerts pass is gone (it left totally-failed
        # MISSED sessions stranded; the reconciler retries every FAILED delivery).

        # --- Pending owner reminders ---
        async with _safe("process_pending_reminders", errors, db):
            reminders_sent = await process_pending_reminders(db)

        # --- Notification-delivery reconciler (the outbox) ---
        # Additive: a no-op over an empty table until dispatch sites enqueue.
        async with _safe("outbox_send_due", errors, db):
            c = await send_due_deliveries(db, now=now)
            outbox_sent = c["sent"]
            outbox_delivered = c["delivered"]
        async with _safe("outbox_derive_promotions", errors, db):
            outbox_promoted = (await derive_session_promotions(db, now=now))["promoted"]
        async with _safe("outbox_poll_receipts", errors, db):
            outbox_delivered += (await poll_expo_receipts(db, now=now))["delivered"]
        async with _safe("outbox_expire_escalate", errors, db):
            outbox_exhausted = (await expire_and_escalate(db, now=now))["expired"]

        # --- Every 10 min: retry pending Stripe customer creation ---
        if now.minute % 10 == 0:
            async with _safe("retry_pending_stripe_customers", errors, db):
                from app.services.stripe_service import retry_pending_stripe_customers

                resolved = await retry_pending_stripe_customers(db)
                if resolved:
                    logger.info("Resolved %d pending Stripe customers", resolved)

        # --- Subscription-lapse reminders (T-7d / T-1d) ---
        # Runs every tick so reminders fire promptly within the 7-day
        # window; idempotency stamps on the subscription rows prevent
        # re-fire. See app/services/sub_lapse_notifications.py.
        async with _safe("process_pending_lapse_reminders", errors, db):
            from app.services.sub_lapse_notifications import (
                process_pending_lapse_reminders,
            )

            lapse_counts = await process_pending_lapse_reminders(db)
            lapse_reminders_sent = lapse_counts["reminders_sent"]

        # --- Hourly: act on stale SMS-unsubscribed account holders ---
        # A user who texted STOP and hasn't responded in the grace
        # window gets their Stripe sub cancelled at period-end + a
        # confirmation push. Hourly cadence is plenty — a one-hour
        # variance on a 14-day timer is invisible.
        if now.minute == 0:
            async with _safe("process_unhandled_sms_unsubscribes", errors, db):
                from app.services.sms_unsubscribe_tasks import (
                    process_unhandled_sms_unsubscribes,
                )

                await process_unhandled_sms_unsubscribes(db)

        # --- Hourly: cleanup expired data + stuck session monitoring ---
        if now.minute == 0:
            async with _safe("cleanup_expired_data", errors, db):
                await cleanup_expired_data(db)

            # Anonymize soft-deleted users whose 30-day grace expired.
            # Hourly cadence is plenty — grace is 30d so a one-hour
            # variance in purge time is invisible. See
            # app/services/account_deletion.py.
            async with _safe("process_pending_purges", errors, db):
                from app.services.account_deletion import process_pending_purges

                purges_done = await process_pending_purges(db)

            async with _safe("stuck session check", errors, db):
                stuck_cutoff = now - timedelta(minutes=10)
                stuck = await crud_session.get_missed_sessions(db)
                stuck_old = [
                    s for s in stuck if s.updated_at and s.updated_at < stuck_cutoff
                ]
                if stuck_old:
                    ids = [str(s.id) for s in stuck_old]
                    # ERROR reaches Bugsnag via the root-logger forwarder
                    # (app/core/error_reporting.py); the ids ride along as metadata.
                    logger.error(
                        "Stuck MISSED sessions older than 10 min: %s",
                        ids,
                        extra={"session_ids": ids},
                    )

    duration_ms = int((time.monotonic() - start) * 1000)
    summary = {
        "tick_at": now.isoformat(),
        "active_processed": active_processed,
        "missed_retried": missed_retried,
        "reminders_sent": reminders_sent,
        "purges_done": purges_done,
        "lapse_reminders_sent": lapse_reminders_sent,
        "outbox_sent": outbox_sent,
        "outbox_delivered": outbox_delivered,
        "outbox_promoted": outbox_promoted,
        "outbox_exhausted": outbox_exhausted,
        "duration_ms": duration_ms,
        "errors": errors,
    }
    logger.info("tick complete: %s", json.dumps(summary, default=str))


# 64-bit key identifying the "only one worker tick at a time" advisory lock.
# Arbitrary, but must never change — an old and a new worker using different
# keys would not exclude each other and could run concurrently.
_WORKER_TICK_LOCK_KEY = 0x4D49484F5F54494B  # b"MIHO_TIK"


async def run_tick_with_lock() -> None:
    """Run one tick, but only if no other tick is already running.

    Only one worker tick may run at a time across the whole system. We enforce
    that with a Postgres *session-level* advisory lock instead of relying on
    deploying exactly one worker replica, so the guarantee holds regardless of
    how the worker is scheduled (ECS RunTask, in-container cron, or more
    than one replica). If the lock is already held, this run is a no-op.

    Why an advisory lock specifically: it is owned by the database *connection*,
    so if this process dies mid-tick, Postgres drops the connection and releases
    the lock automatically — a crashed worker can never wedge the system. A lock
    row / lock file / Redis key would instead need a TTL and could strand on a
    crash.

    GOTCHA — dedicated connection, never a pooled one:
        The lock is held on its own connection, kept open for the entire tick,
        and released with an explicit pg_advisory_unlock in `finally`. This is
        load-bearing: returning a connection to the pool does NOT release a
        session-level advisory lock (the physical socket stays open in the pool),
        so relying on pool-return would leak the lock — it would silently outlive
        the work and block every future tick, or be re-entered by an unrelated
        checkout of the same pooled connection. Only an explicit unlock or a real
        disconnect (e.g. the process dying) releases it. The tick's own DB work
        uses separate sessions from AsyncSessionLocal, so its pooled connections
        are independent of this lock connection.

    GOTCHA — never route this through a transaction-mode pooler (PgBouncer):
        Session-level advisory locks require a stable backend session for their
        whole lifetime. RDS Postgres can sit behind RDS Proxy (or any PgBouncer);
        in *transaction* pooling mode the physical backend is
        not pinned to one client between statements, so pg_try_advisory_lock and
        pg_advisory_unlock can land on different backends and the lock silently
        stops excluding anything. This connection must reach Postgres directly
        (port 5432), never a transaction-mode pooler. The app connects directly
        via SQLAlchemy's own pool today, so this holds — revisit if PgBouncer is
        ever enabled.
    """
    async with async_engine.connect() as lock_conn:
        acquired = await lock_conn.scalar(
            text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _WORKER_TICK_LOCK_KEY},
        )
        if not acquired:
            logger.info(
                "Another worker tick holds the advisory lock — skipping this run"
            )
            return
        try:
            await tick()
        finally:
            # Required — pool-return does not release a session-level lock (see
            # the dedicated-connection gotcha above), so unlock explicitly.
            await lock_conn.scalar(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": _WORKER_TICK_LOCK_KEY},
            )


if __name__ == "__main__":
    from app.core.config import settings
    from app.core.startup_checks import run_production_startup_checks

    # Same boot contract as the web + worker_loop (see there).
    run_production_startup_checks(settings)
    try:
        asyncio.run(run_tick_with_lock())
    except Exception:
        logger.exception("Worker tick failed")
        sys.exit(1)
