import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import (
    get_current_user_with_profile,
    require_subscription_access,
)
from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.crud import (
    crud_alert,
    crud_circle_of_trust,
    crud_session,
    crud_session_reminder,
)
from app.models.circle_of_trust import ContactStatus
from app.models.session import Session as SessionModel
from app.models.session import SessionStatus, SessionType
from app.models.user import User as UserModel
from app.schemas.session import (
    LocationPoint,
    RetentionAdjust,
    Session,
    SessionCreate,
    SessionExtend,
    SessionUpdateRequest,
)
from app.services.file_upload import upload_image
from app.services.session_tasks import (
    complete_session_with_all_clear,
    process_overdue,
    schedule_reminders_for_session,
)

logger = logging.getLogger(__name__)

router = APIRouter()


COMPLETABLE_STATUSES = {
    SessionStatus.ACTIVE.value,
    SessionStatus.MISSED.value,
    SessionStatus.ALERTED.value,
}


def _require_active_session(session) -> None:
    if session.status != SessionStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Session is not active"
        )


async def _with_owner_status_flags(db: AsyncSession, session: SessionModel) -> Session:
    """Serialize a session with the server-truth flags the owner's surfaces
    render from: alert_acknowledged ("someone's on their way") and
    circle_unreachable ("we couldn't reach anyone"). Both are computed only
    here — everywhere else they keep their fail-safe False defaults."""
    from app.services.notification_outbox import is_circle_unreachable

    response = Session.model_validate(session)
    response.alert_acknowledged = await crud_alert.has_acknowledged_alert(
        db, session_id=session.id
    )
    response.circle_unreachable = await is_circle_unreachable(db, session)
    # Did ANY alert ever fire? Drives the summary screen's honest past tense
    # ("Was shared with your Circle" vs "Nothing was shared with your Circle").
    response.was_alerted = await crud_alert.session_has_alerts(
        db, session_id=session.id
    )
    return response


@router.get("", response_model=list[Session])
async def get_sessions(
    skip: int = 0,
    limit: int = 20,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    sessions = await crud_session.get_user_sessions(
        db, user_id=current_user.id, skip=skip, limit=limit
    )
    return sessions


@router.get("/active", response_model=Session | None)
async def get_active_session(
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    """The user's current non-terminal session (ACTIVE, MISSED or ALERTED).

    MISSED/ALERTED are included on purpose: the mobile store reloads from
    this endpoint on every mount, so returning null for a live incident
    would erase the owner's escalation UI and end the Live Activity
    mid-incident. The server-truth status flags are computed here for the
    same reason — a remount must land on the same truth the poll shows.
    """
    session = await crud_session.get_active_session(db, user_id=current_user.id)
    if session is None:
        return None
    return await _with_owner_status_flags(db, session)


@router.put("/{session_id}/retention", response_model=Session)
async def adjust_session_retention(
    session_id: UUID,
    adjust: RetentionAdjust | None = None,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    """Adjust the post-session data purge date by ±RETENTION_EXTENSION_DAYS.

    Owner-only, repeatable, and only while the data still exists — once
    purge_after passes, the worker has deleted the photos/locations and
    there is nothing left to keep (docs/flow-review.md E2/3.10). No body
    keeps the historical behavior (one extension).

    Reductions (owner decision 2026-07-19) only walk back extensions the
    owner personally added: the result is clamped to the FLOOR — the higher
    of the original deletion date (session end + SESSION_DATA_RETENTION_DAYS,
    recomputable forever from actual_return_time / cancelled_at) and now.
    Inside the original window the floor IS the original date, so a hostile
    phone-holder can never beat the evidence window; there is deliberately
    no owner-facing "delete now" for the same reason.
    """
    days = adjust.days if adjust is not None else settings.RETENTION_EXTENSION_DAYS
    if abs(days) != settings.RETENTION_EXTENSION_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Retention can only be adjusted by "
                f"±{settings.RETENTION_EXTENSION_DAYS} days"
            ),
        )
    session = await crud_session.get_owned_or_404(
        db, id=session_id, owner=current_user, resource_name="Session"
    )
    now = datetime.now(UTC)
    if session.status == SessionStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session is still active — retention starts when it ends",
        )
    if session.purge_after is None or session.purge_after <= now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session data has already been deleted",
        )

    new_purge_after = session.purge_after + timedelta(days=days)
    if days < 0:
        # Neutral session-end anchor: when the owner marked safe, or when an
        # admin cancelled. A terminal session missing both is a legacy edge —
        # the floor is unrecoverable, so reduction is refused (extend-only).
        session_end = session.actual_return_time or session.cancelled_at
        if session_end is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Retention cannot be reduced for this session",
            )
        floor = max(
            session_end + timedelta(days=settings.SESSION_DATA_RETENTION_DAYS),
            now,
        )
        if session.purge_after <= floor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Retention is already at its minimum",
            )
        new_purge_after = max(new_purge_after, floor)

    session.purge_after = new_purge_after
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/{session_id}", response_model=Session)
async def get_session(
    session_id: UUID,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    """Fetch one session by id (owner only).

    The mobile active-session screen polls this to learn the server-truth
    status transition (ACTIVE → MISSED → ALERTED) — the client clock must
    never claim the circle was notified (docs/flow-review.md C1/3.4).

    The poll endpoints (here and /active) are also where alert_acknowledged
    ("someone is on their way") and circle_unreachable ("we couldn't reach
    anyone") are populated — both server truth, fail-safe False elsewhere.
    """
    session = await crud_session.get_owned_or_404(
        db, id=session_id, owner=current_user, resource_name="Session"
    )
    return await _with_owner_status_flags(db, session)


@router.post("", response_model=Session, status_code=status.HTTP_201_CREATED)
async def create_session(
    session_in: SessionCreate,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    if session_in.session_type == SessionType.SOS:
        # SOS is free, always — an emergency must never be blocked (or worse,
        # silently queued into a fake alarm) by billing state. Only scheduled
        # check-in sessions are subscription-gated.
        return await _create_sos_session(db, current_user, session_in)
    await require_subscription_access(db, current_user)
    return await _create_checkin_session(db, current_user, session_in)


async def _create_checkin_session(
    db: AsyncSession, user: UserModel, session_in: SessionCreate
) -> SessionModel:
    active_session = await crud_session.get_active_session(db, user_id=user.id)
    if active_session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You already have an active session. Complete it before creating a new one.",
        )

    # The floor applies wherever the deadline is SET (owner decision
    # 2026-07-19); SOS never passes through here (deadline = now by design).
    min_deadline = datetime.now(UTC) + timedelta(
        minutes=settings.MIN_SESSION_LEAD_MINUTES
    )
    if (
        session_in.expected_return_time is not None
        and session_in.expected_return_time < min_deadline
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Expected return time must be at least "
                f"{settings.MIN_SESSION_LEAD_MINUTES} minutes from now"
            ),
        )

    circle_members = await crud_circle_of_trust.get_user_contacts(
        db, user_id=user.id, status=ContactStatus.ACTIVE
    )
    if not circle_members:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You need at least one active contact in your circle to start a session",
        )

    session = await crud_session.create_session(db, user_id=user.id, obj_in=session_in)

    await schedule_reminders_for_session(db, session.id, session.expected_return_time)

    return session


async def _create_sos_session(
    db: AsyncSession, user: UserModel, session_in: SessionCreate
) -> SessionModel:
    circle_members = await crud_circle_of_trust.get_user_contacts(
        db, user_id=user.id, status=ContactStatus.ACTIVE
    )
    if not circle_members:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active contacts in your circle to alert",
        )

    # SOS during a live check-in is the SAME outing, escalated — not a
    # parallel session (owner decision 2026-07-18). Convert the row in place
    # so the circle's alert page carries everything gathered so far
    # (destination, outfit photo, photos, location trail). Only ACTIVE
    # sessions convert: once MISSED/ALERTED the circle has already been
    # alerted for the miss, and a fresh SOS session correctly gives them a
    # distinct PANIC alert instead.
    existing = await crud_session.get_active_session(db, user_id=user.id)
    if existing is not None and existing.status == SessionStatus.ACTIVE.value:
        session = existing
        session.session_type = SessionType.SOS.value
        # Accelerated end time: the outing ends NOW.
        session.expected_return_time = datetime.now(UTC)
        # Emergency posture: the circle needs to find them.
        session.location_sharing_enabled = True
        await db.commit()
        # The old deadline's pending server reminder (T-0 SMS) is moot.
        await crud_session_reminder.delete_for_session(db, session_id=session.id)
    else:
        session = await crud_session.create_session(
            db, user_id=user.id, obj_in=session_in
        )

    # Attach the last-known location the app sent (if any) BEFORE dispatching,
    # so the very first SOS alert already carries a map pin — the dispatch is
    # inline, before location tracking would produce its own update.
    if session_in.latitude is not None and session_in.longitude is not None:
        try:
            await crud_session.update_location(
                db,
                session=session,
                latitude=session_in.latitude,
                longitude=session_in.longitude,
                battery_level=session_in.battery_level,
                battery_state=session_in.battery_state,
            )
        except Exception:
            logger.exception(
                "Failed to attach SOS initial location for session %s", session.id
            )

    # SOS is an emergency: dispatch immediately rather than waiting for the
    # next worker tick. The grace-period overdue scan (GRACE_PERIOD_MINUTES)
    # would otherwise delay a panic press by ~2-3 minutes. The worker remains
    # a backstop — if this inline dispatch partially fails, the session is
    # left MISSED and retried on the next tick.
    try:
        await process_overdue(db, session.id)
    except Exception:
        logger.exception("Inline SOS dispatch failed for session %s", session.id)

    # The inline dispatch flips status via raw UPDATEs that never touch this
    # ORM instance (expire_on_commit=False) — refresh so the response carries
    # the real post-dispatch status (missed/alerted), not a stale "active".
    # The mobile alarm card renders server truth from this response.
    await db.refresh(session)
    return session


@router.post("/outfit-photos", response_model=dict)
async def upload_outfit_photo(
    file: UploadFile = File(...),
    session_id: UUID = Form(...),
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    session = await crud_session.get_owned_or_404(
        db, id=session_id, owner=current_user, resource_name="session"
    )

    url = await upload_image(file, "outfit-photos", current_user.id, max_size_mb=10)

    session.outfit_photo_url = url
    await db.commit()

    return {"outfit_photo_url": url}


@router.put("/{session_id}/complete", response_model=Session)
async def complete_session(
    session_id: UUID,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    session = await crud_session.get_owned_or_404(
        db,
        id=session_id,
        owner=current_user,
        resource_name="session",
        custom_error="You can only complete your own sessions",
    )

    if session.status not in COMPLETABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session cannot be completed",
        )

    # Shared mark-safe path (also used by admin mark-safe) — the
    # completion side effects (alert resolution, supersedes, all-clear
    # broadcast) live in ONE place.
    return await complete_session_with_all_clear(db, session, current_user)


@router.put("/{session_id}/extend", response_model=Session)
async def extend_session(
    session_id: UUID,
    extend_data: SessionExtend,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    session = await crud_session.get_owned_or_404(
        db,
        id=session_id,
        owner=current_user,
        resource_name="session",
        custom_error="You can only extend your own sessions",
    )

    _require_active_session(session)

    # A negative delta reduces the deadline (correcting an accidental extend).
    # The minimum-lead floor applies wherever the deadline is SET (owner
    # decision 2026-07-19): a reduction may never leave less than
    # MIN_SESSION_LEAD_MINUTES on the clock — reducing to/past now would
    # immediately fire the circle alert.
    prospective = session.expected_return_time + timedelta(
        minutes=extend_data.minutes_to_extend
    )
    if prospective < datetime.now(UTC) + timedelta(
        minutes=settings.MIN_SESSION_LEAD_MINUTES
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That reduction would leave less than "
                f"{settings.MIN_SESSION_LEAD_MINUTES} minutes on the session"
            ),
        )

    session = await crud_session.extend_session(
        db, session=session, minutes=extend_data.minutes_to_extend
    )

    await crud_session_reminder.delete_for_session(db, session_id=session.id)
    await schedule_reminders_for_session(db, session.id, session.expected_return_time)

    return session


# Appends one reading (a session_update row) to the session's locations and
# refreshes its last-known position. Battery-only readings (no coords) are
# accepted too. Returns the updated parent session, not the appended point —
# hence 200, not 201.
@router.post("/{session_id}/locations", response_model=Session)
async def update_location(
    session_id: UUID,
    location: SessionUpdateRequest,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    session = await crud_session.get_owned_or_404(
        db,
        id=session_id,
        owner=current_user,
        resource_name="session",
        custom_error="You can only update your own session location",
    )

    # Battery has no toggle and is always capturable, so a battery-only update
    # is accepted regardless. Only a LOCATION update requires the toggle on.
    if location.latitude is not None and not session.location_sharing_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Location sharing is not enabled for this session",
        )

    session = await crud_session.update_location(
        db,
        session=session,
        latitude=location.latitude,
        longitude=location.longitude,
        battery_level=location.battery_level,
        battery_state=location.battery_state,
    )

    return session


@router.get("/{session_id}/locations", response_model=list[LocationPoint])
async def get_location_history(
    session_id: UUID,
    current_user: UserModel = Depends(get_current_user_with_profile),
    db: AsyncSession = Depends(get_db),
):
    session = await crud_session.get(db, id=session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    is_owner = session.user_id == current_user.id
    if not is_owner:
        alerts = await crud_alert.get_session_alerts(db, session_id=session_id)
        has_alert = any(a.sent_to_user_id == current_user.id for a in alerts)
        if not has_alert:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this session's location history",
            )

    return await crud_session.get_location_history(db, session_id=session_id)
