"""CRUD for SessionReminder.

Reminders are pre-calculated rows the cron picks up and dispatches.
create_reminders_for_session builds rows at each ALERT_REMINDER_TIMES
interval; get_pending returns unsent rows where fire_at <= now().

Related: models/session_reminder.py, services/session_tasks.py
"""
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.session_reminder import SessionReminder


class CRUDSessionReminder:
    async def create_reminders_for_session(
        self,
        db: AsyncSession,
        *,
        session_id: UUID,
        deadline: datetime,
    ) -> list[SessionReminder]:
        """Insert the at-deadline reminder row (still-in-the-future only).

        Owner decision 2026-07-18: every reminder PUSH is a client-scheduled
        local notification now (fires in dead zones / backend outages), so the
        server only schedules the minutes == 0 rung — the at-deadline
        "time's up" SMS, which only the server can send. Pre-deadline rungs
        (30/10) are no longer created here.
        """
        now = datetime.now(UTC)
        rows: list[SessionReminder] = []
        for minutes in settings.ALERT_REMINDER_TIMES:
            if minutes != 0:
                continue
            fire_at = deadline - timedelta(minutes=minutes)
            if fire_at <= now:
                continue
            row = SessionReminder(
                session_id=session_id,
                fire_at=fire_at,
                minutes_before=minutes,
            )
            db.add(row)
            rows.append(row)
        await db.commit()
        for r in rows:
            await db.refresh(r)
        return rows

    async def get_pending(self, db: AsyncSession) -> list[SessionReminder]:
        """All unsent reminders whose fire time has passed."""
        now = datetime.now(UTC)
        result = await db.execute(
            select(SessionReminder)
            .where(SessionReminder.fire_at <= now)
            .where(SessionReminder.sent_at.is_(None))
        )
        return result.scalars().all()

    async def mark_sent(self, db: AsyncSession, *, reminder_id: UUID) -> None:
        await db.execute(
            update(SessionReminder)
            .where(SessionReminder.id == reminder_id)
            .values(sent_at=datetime.now(UTC))
        )
        await db.commit()

    async def delete_for_session(self, db: AsyncSession, *, session_id: UUID) -> int:
        """Used when extending or completing a session — clears outstanding reminders."""
        result = await db.execute(
            delete(SessionReminder).where(SessionReminder.session_id == session_id)
        )
        await db.commit()
        return result.rowcount


crud_session_reminder = CRUDSessionReminder()
