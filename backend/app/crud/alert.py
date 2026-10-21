"""Alert CRUD — the business Alert row about a circle member.

Per-channel delivery + retry now live in notification_deliveries (the outbox);
the Alert.status is a rollup of its delivery rows (services/notification_outbox.
rollup_alert_status). Key methods here: create_alert, mark_acknowledged,
resolve_session_alerts (user marked safe).

Related: models/alert.py, models/notification_delivery.py,
         services/notification_outbox.py
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload

from app.core.config import settings
from app.crud.base import CRUDBase
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember
from app.models.session import Session, SessionStatus
from app.schemas.alert import AlertCreate, AlertUpdate


def stale_incident_cutoff(now: datetime | None = None) -> datetime:
    """Deadline before which a still-MISSED/ALERTED session counts as a
    never-resolved incident that is "no longer current" (ALERT_PAGE_MAX_AGE_DAYS
    from the deadline — .claude/rules/domain-sessions-alerts.md, "Never-resolved
    incidents"). Shared by the web predicate (routes_web._is_no_longer_current)
    and the SQL filter in get_unacknowledged_alerts so the two can't drift."""
    return (now or datetime.now(UTC)) - timedelta(days=settings.ALERT_PAGE_MAX_AGE_DAYS)


class CRUDAlert(CRUDBase[Alert, AlertCreate, AlertUpdate]):
    async def get_session_alerts(
        self, db: AsyncSession, *, session_id: UUID
    ) -> list[Alert]:
        result = await db.execute(
            select(Alert)
            .where(Alert.session_id == session_id)
            .order_by(Alert.sent_at.desc())
        )
        return result.scalars().all()

    async def get_user_alerts(
        self, db: AsyncSession, *, user_id: UUID, skip: int = 0, limit: int = 20
    ) -> list[Alert]:
        result = await db.execute(
            select(Alert)
            .options(joinedload(Alert.session).joinedload(Session.user))
            .where(Alert.sent_to_user_id == user_id)
            .order_by(Alert.sent_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.unique().scalars().all()

    async def create_alert(self, db: AsyncSession, *, obj_in: AlertCreate) -> Alert:
        db_obj = Alert(
            session_id=obj_in.session_id,
            sent_to_user_id=obj_in.sent_to_user_id,
            sent_to_phone_id=obj_in.sent_to_phone_id,
            alert_type=obj_in.alert_type,
            message=obj_in.message,
            status=AlertStatus.SENT,
            sent_at=datetime.now(UTC),
        )
        return await self._commit_and_refresh(db, db_obj)

    async def mark_acknowledged(self, db: AsyncSession, *, alert: Alert) -> Alert:
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_at = datetime.now(UTC)
        return await self._commit_and_refresh(db, alert)

    async def create_for_circle(
        self,
        db: AsyncSession,
        *,
        circle_members: list[CircleOfTrustMember],
        alert_type: AlertType,
        message: str,
        session_id: UUID | None = None,
    ) -> list[Alert]:
        """Create an alert for each circle member that has an app account."""
        alerts = []
        for member in circle_members:
            if not member.contact_user:
                continue
            alert = await self.create_alert(
                db,
                obj_in=AlertCreate(
                    session_id=session_id,
                    sent_to_user_id=member.contact_user.id,
                    alert_type=alert_type,
                    message=message,
                ),
            )
            alerts.append(alert)
        return alerts

    async def resolve_session_alerts(
        self, db: AsyncSession, *, session_id: UUID
    ) -> int:
        """Mark all non-terminal alerts for a session as resolved (user marked safe)."""
        from sqlalchemy import update

        terminal = {AlertStatus.ACKNOWLEDGED.value, AlertStatus.FAILED.value}
        now = datetime.now(UTC)
        result = await db.execute(
            update(Alert)
            .where(
                and_(
                    Alert.session_id == session_id,
                    Alert.status.notin_(terminal),
                )
            )
            .values(status=AlertStatus.RESOLVED.value, resolved_at=now)
        )
        await db.commit()
        return result.rowcount

    async def has_acknowledged_alert(
        self, db: AsyncSession, *, session_id: UUID
    ) -> bool:
        """True when any alert for the session was acknowledged by a circle member.

        Feeds Session.alert_acknowledged on GET /sessions/{id} so the owner's
        surfaces (active-session screen, Live Activity) can state "someone is
        on their way" from server truth.
        """
        result = await db.execute(
            select(Alert.id)
            .where(
                and_(
                    Alert.session_id == session_id,
                    Alert.status == AlertStatus.ACKNOWLEDGED,
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def session_has_alerts(self, db: AsyncSession, *, session_id: UUID) -> bool:
        """True when ANY alert was ever dispatched for the session.

        Feeds Session.was_alerted on the owner detail endpoint — the session
        summary's honest past tense ("Was shared with your Circle" vs
        "Nothing was shared with your Circle"); terminal status alone can't
        distinguish the two histories.
        """
        result = await db.execute(
            select(Alert.id).where(Alert.session_id == session_id).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_unacknowledged_alerts(
        self, db: AsyncSession, *, user_id: UUID
    ) -> list[Alert]:
        """Alerts still worth surfacing to this recipient: not yet
        acknowledged AND not already resolved (user marked safe), for an
        incident that is still current — not COMPLETED (an all-clear), not
        CANCELLED (a closed false alarm), and not a never-resolved
        MISSED/ALERTED session past stale_incident_cutoff() (the public page
        shows it as "no longer current"). Feeds the nav badge (and the
        /alerts page's count), so it never nags about an incident that's
        over."""
        cutoff = stale_incident_cutoff()
        result = await db.execute(
            select(Alert)
            .join(Alert.session)
            .options(contains_eager(Alert.session).joinedload(Session.user))
            .where(
                and_(
                    Alert.sent_to_user_id == user_id,
                    Alert.status.notin_(
                        (AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED)
                    ),
                    Session.status.notin_(
                        (SessionStatus.COMPLETED, SessionStatus.CANCELLED)
                    ),
                    or_(
                        Session.status.notin_(
                            (SessionStatus.MISSED, SessionStatus.ALERTED)
                        ),
                        Session.expected_return_time >= cutoff,
                    ),
                )
            )
            .order_by(Alert.sent_at.desc())
        )
        return result.unique().scalars().all()


crud_alert = CRUDAlert(Alert)
