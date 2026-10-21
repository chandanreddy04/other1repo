"""Session queries and atomic status transitions.

claim_for_processing() uses UPDATE … WHERE status='active' RETURNING id
so only one worker gets a given session. get_overdue_sessions applies the
grace period before surfacing sessions for processing.

Related: models/session.py, services/session_tasks.py, worker_tick.py
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud.base import CRUDBase
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate as SessionUpdateModel
from app.schemas.session import SessionCreate, SessionUpdate

# Statuses that are still "the user's current session". MISSED/ALERTED are
# live incidents, not history — the mobile store reloads from /sessions/active
# on every mount, so excluding them would erase the owner's escalation UI
# (and kill the Live Activity) mid-incident. Only COMPLETED/CANCELLED end it.
NON_TERMINAL_STATUSES = (
    SessionStatus.ACTIVE.value,
    SessionStatus.MISSED.value,
    SessionStatus.ALERTED.value,
)


class CRUDSession(CRUDBase[Session, SessionCreate, SessionUpdate]):
    async def get_active_session(
        self, db: AsyncSession, *, user_id: UUID
    ) -> Session | None:
        """Newest non-terminal session, preferring a truly ACTIVE one.

        More than one non-terminal row per user is possible (an SOS pressed
        during a check-in, or a new session after an old one went MISSED), so
        this must never assume uniqueness: ACTIVE first, then newest, one row.
        """
        result = await db.execute(
            select(Session)
            .where(
                and_(
                    Session.user_id == user_id,
                    Session.status.in_(NON_TERMINAL_STATUSES),
                )
            )
            .order_by(
                (Session.status != SessionStatus.ACTIVE.value).asc(),
                Session.created_at.desc(),
            )
            .limit(1)
        )
        return result.scalars().first()

    async def get_user_sessions(
        self, db: AsyncSession, *, user_id: UUID, skip: int = 0, limit: int = 20
    ) -> list[Session]:
        result = await db.execute(
            select(Session)
            .where(Session.user_id == user_id)
            .order_by(Session.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    async def create_session(
        self, db: AsyncSession, *, user_id: UUID, obj_in: SessionCreate
    ) -> Session:
        db_obj = Session(
            user_id=user_id,
            session_type=obj_in.session_type.value,
            expected_return_time=obj_in.expected_return_time,
            tz_offset_minutes=obj_in.tz_offset_minutes,
            destination=obj_in.destination,
            outfit_photo_url=obj_in.outfit_photo_url,
            outfit_photo_uploaded_at=datetime.now(UTC)
            if obj_in.outfit_photo_url
            else None,
            location_sharing_enabled=obj_in.location_sharing_enabled,
            status=SessionStatus.ACTIVE.value,
        )
        return await self._commit_and_refresh(db, db_obj)

    async def complete_session(self, db: AsyncSession, *, session: Session) -> Session:
        session.status = SessionStatus.COMPLETED.value
        session.actual_return_time = datetime.now(UTC)
        # Data survives the session for the retention window (owner can
        # extend from History) — was purge-on-next-tick before (E2/3.10).
        session.purge_after = datetime.now(UTC) + timedelta(
            days=settings.SESSION_DATA_RETENTION_DAYS
        )
        return await self._commit_and_refresh(db, session)

    async def extend_session(
        self, db: AsyncSession, *, session: Session, minutes: int
    ) -> Session:
        session.expected_return_time = session.expected_return_time + timedelta(
            minutes=minutes
        )
        return await self._commit_and_refresh(db, session)

    async def claim_for_processing(
        self, db: AsyncSession, *, session_id: UUID
    ) -> UUID | None:
        """Atomically flip ACTIVE → MISSED. Returns the session id if claimed, None
        if another worker already claimed it. Acts as the coordination gate that
        prevents two cron iterations from processing the same session twice.
        """
        result = await db.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.status == SessionStatus.ACTIVE.value,
            )
            .values(status=SessionStatus.MISSED.value)
            .returning(Session.id)
        )
        row = result.scalar_one_or_none()
        await db.commit()
        return row

    async def mark_as_alerted(
        self, db: AsyncSession, *, session_id: UUID
    ) -> UUID | None:
        """Atomically flip MISSED → ALERTED after all dispatches complete."""
        result = await db.execute(
            update(Session)
            .where(
                Session.id == session_id,
                Session.status == SessionStatus.MISSED.value,
            )
            .values(status=SessionStatus.ALERTED.value)
            .returning(Session.id)
        )
        row = result.scalar_one_or_none()
        await db.commit()
        return row

    async def get_missed_sessions(self, db: AsyncSession) -> list[Session]:
        """All MISSED sessions — cron retries dispatch on each tick."""
        result = await db.execute(
            select(Session).where(Session.status == SessionStatus.MISSED.value)
        )
        return result.scalars().all()

    async def update_location(
        self,
        db: AsyncSession,
        *,
        session: Session,
        latitude: float | None = None,
        longitude: float | None = None,
        battery_level: float | None = None,
        battery_state: str | None = None,
    ) -> Session:
        entry = SessionUpdateModel(
            session_id=session.id,
            latitude=latitude,
            longitude=longitude,
            battery_level=battery_level,
            battery_state=battery_state,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(session)
        return session

    async def get_location_history(
        self, db: AsyncSession, *, session_id: UUID
    ) -> list[SessionUpdateModel]:
        # The location trail is coord-bearing rows only — battery-only
        # heartbeats carry no point to plot.
        result = await db.execute(
            select(SessionUpdateModel)
            .where(
                SessionUpdateModel.session_id == session_id,
                SessionUpdateModel.latitude.isnot(None),
            )
            .order_by(SessionUpdateModel.recorded_at.asc())
        )
        return result.scalars().all()

    async def get_overdue_sessions(
        self, db: AsyncSession, *, grace_minutes: int = 0
    ) -> list[Session]:
        cutoff = datetime.now(UTC) - timedelta(minutes=grace_minutes)
        result = await db.execute(
            select(Session).where(
                and_(
                    Session.status == SessionStatus.ACTIVE.value,
                    Session.expected_return_time < cutoff,
                )
            )
        )
        return result.scalars().all()


crud_session = CRUDSession(Session)
