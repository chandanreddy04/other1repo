"""Acknowledging an alert, with an SMS-only broadcast to owner + circle.

The first contact to respond acknowledges the alert so the owner knows it
was seen (by WHOM — their own contact) and other members know SOMEONE
responded (never who — identity stays private within the circle, owner
decision 2026-07-18). Copy states exactly what a tap proves: an
acknowledgement, never "on their way". Called only from the public
(tokenized) alert page's Acknowledge button — how an SMS-only contact with
no app and no account can still respond. The web dashboard's htmx
acknowledge was removed 2026-09-23, and the dashboard itself the same day. The mobile API acknowledge endpoint (`PUT /alerts/{id}/acknowledge`)
lost its last caller on 2026-09-22 and was removed the same day.

Related: web/routes_web.py (public alert page),
web/routes_htmx_profile.py, services/notification_constants.py.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.crud.alert import crud_alert
from app.crud.notification_delivery import crud_notification_delivery as crud_nd
from app.models.alert import Alert, AlertStatus
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import NotificationKind
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.services.notification_constants import (
    ALERT_ACKNOWLEDGED_MEMBER_BODY,
    ALERT_ACKNOWLEDGED_MEMBER_BODY_NO_NAME,
    ALERT_ACKNOWLEDGED_OWNER_BODY,
)
from app.services.notification_outbox import (
    build_broadcast_rows,
    enqueue_and_send,
)

logger = logging.getLogger(__name__)


async def acknowledger_display_name(
    db: AsyncSession, alert: Alert, session: Session
) -> str:
    """Display name of the contact this alert was sent to."""
    if alert.sent_to_user_id:
        result = await db.execute(select(User).where(User.id == alert.sent_to_user_id))
        user = result.scalar_one_or_none()
        if user and user.full_name:
            return user.full_name
    if alert.sent_to_phone_id:
        member_result = await db.execute(
            select(CircleOfTrustMember).where(
                and_(
                    CircleOfTrustMember.user_id == session.user_id,
                    CircleOfTrustMember.contact_phone_number_id
                    == alert.sent_to_phone_id,
                )
            )
        )
        member = member_result.scalars().first()
        if member and member.display_name:
            return member.display_name
    return "Someone"


async def acknowledge_alert(db: AsyncSession, *, alert: Alert) -> str:
    """Mark the alert ACKNOWLEDGED and broadcast it (SMS-only).

    Returns the acknowledger's display name (used only owner-facing).
    Idempotent-ish: re-acknowledging an already-acknowledged alert
    re-broadcasts nothing. Broadcast failures never fail the acknowledgement itself.

    No-ops entirely once the incident is over (alert RESOLVED, or session
    COMPLETED/CANCELLED): a late tap — e.g. a page loaded before the owner
    marked safe — must not flip a resolved alert back to "claimed" and
    broadcast "{claimer} is on it" after the all-clear went out. This is the
    single guard for the only acknowledge surface (the public alert page).
    """
    result = await db.execute(
        select(Session)
        .options(selectinload(Session.user))
        .where(Session.id == alert.session_id)
    )
    session = result.scalar_one_or_none()

    session_over = session is not None and str(session.status) in (
        SessionStatus.COMPLETED.value,
        SessionStatus.CANCELLED.value,
    )
    if alert.status == AlertStatus.RESOLVED or session_over:
        return "Someone"

    already_acknowledged = alert.status == AlertStatus.ACKNOWLEDGED
    await crud_alert.mark_acknowledged(db, alert=alert)

    if not session or already_acknowledged:
        return "Someone"

    # Someone's on it — stop any pending circle re-nudge for this session.
    await crud_nd.supersede(
        db, session_id=session.id, kind=NotificationKind.CIRCLE_RENUDGE
    )
    await db.commit()

    acknowledger = await acknowledger_display_name(db, alert, session)
    owner = session.user
    now = datetime.now(UTC)
    data = {"session_id": str(session.id), "type": "alert_acknowledged"}

    # SMS-ONLY broadcast (owner decision 2026-07-18) — no pushes. The owner
    # learns WHO acknowledged (their own contact); every other ACTIVE member
    # — app or no app — only learns that SOMEONE did: the acknowledger's
    # identity is never revealed to the rest of the circle. Routed through
    # the outbox so a transient failure retries.
    rows = build_broadcast_rows(
        NotificationKind.ALERT_ACKNOWLEDGED,
        scope_id=session.id,
        now=now,
        title=None,
        body=ALERT_ACKNOWLEDGED_OWNER_BODY.format(acknowledger=acknowledger),
        data=data,
        recipient_phone_id=owner.phone_number_id,
        session_id=session.id,
        occurrence=str(alert.id),
    )

    members_result = await db.execute(
        select(CircleOfTrustMember)
        .options(selectinload(CircleOfTrustMember.contact_user))
        .where(
            and_(
                CircleOfTrustMember.user_id == session.user_id,
                CircleOfTrustMember.status == ContactStatus.ACTIVE,
            )
        )
    )
    # An alert's owner always has a full_name (required at signup) — the old
    # "them" fallback ("them's alert was acknowledged") was defensive code
    # for a state that can't happen; owner-approved 2026-09-27 fallback body
    # for the one case that IS possible (a hard-purged owner, full_name
    # nulled) is a plain sentence instead of an interpolated grammar bug.
    member_body = (
        ALERT_ACKNOWLEDGED_MEMBER_BODY.format(owner=owner.full_name.split(" ")[0])
        if owner.full_name
        else ALERT_ACKNOWLEDGED_MEMBER_BODY_NO_NAME
    )
    for m in members_result.scalars().all():
        cu = m.contact_user
        # Exclude the acknowledger BOTH ways — by account (app claim) and by
        # phone (public-page claim) — so they never text themselves; and the
        # owner's own membership rows (the owner gets their named SMS above).
        if cu is not None and cu.id in (alert.sent_to_user_id, owner.id):
            continue
        if (
            alert.sent_to_phone_id is not None
            and m.contact_phone_number_id == alert.sent_to_phone_id
        ):
            continue
        rows.extend(
            build_broadcast_rows(
                NotificationKind.ALERT_ACKNOWLEDGED,
                scope_id=session.id,
                now=now,
                title=None,
                body=member_body,
                data=data,
                recipient_phone_id=m.contact_phone_number_id,
                session_id=session.id,
                occurrence=str(alert.id),
            )
        )

    await enqueue_and_send(db, rows, now=now)
    return acknowledger
