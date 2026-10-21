from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.core.error_reporting import ErrorReportingSmokeTestError
from app.core.error_reporting import is_configured as error_reporting_configured
from app.core.error_reporting import notify as report_error
from app.core.version import git_sha
from app.crud import crud_alert
from app.crud import crud_notification_delivery as crud_nd
from app.models.alert import Alert
from app.models.notification_delivery import NotificationKind
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.models.subscription import Subscription
from app.models.user import User
from app.services.blob_storage import BlobStorageService
from app.services.session_tasks import (
    complete_session_with_all_clear,
    purge_session_data,
)
from app.web.admin_registry import register_all
from app.web.admin_views import _write_audit_log
from app.web.csrf import (
    get_or_create_csrf_token,
    set_csrf_cookie,
    validate_csrf_token,
)
from app.web.deps import get_current_admin

templates = Jinja2Templates(directory="app/web/templates")
# admin/base_admin.html's "Main Site" link points at the marketing site
# (owner decision 2026-09-23: marketing lives only on marketing-site).
templates.env.globals["marketing_origin"] = settings.MARKETING_ORIGIN

admin_router = APIRouter(prefix="/admin", tags=["admin"])

# Register CRUD views for all entities
register_all(admin_router)


@admin_router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    total_users = (await db.execute(select(func.count()).select_from(User))).scalar()
    new_users_today = (
        await db.execute(
            select(func.count()).select_from(User).where(User.created_at >= today_start)
        )
    ).scalar()
    active_sessions = (
        await db.execute(
            select(func.count()).select_from(Session).where(Session.status == "active")
        )
    ).scalar()
    missed_sessions_today = (
        await db.execute(
            select(func.count())
            .select_from(Session)
            .where(
                Session.status.in_(["missed"]),
                Session.created_at >= today_start,
            )
        )
    ).scalar()
    alerts_today = (
        await db.execute(
            select(func.count())
            .select_from(Alert)
            .where(Alert.created_at >= today_start)
        )
    ).scalar()
    active_subscriptions = (
        await db.execute(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status == "active")
        )
    ).scalar()
    total_sessions = (
        await db.execute(select(func.count()).select_from(Session))
    ).scalar()

    recent_result = await db.execute(
        select(Session)
        .options(joinedload(Session.user))
        .order_by(Session.created_at.desc())
        .limit(10)
    )
    recent_sessions = recent_result.scalars().unique().all()

    csrf_token = get_or_create_csrf_token(request)
    response = templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "request": request,
            "active_section": "dashboard",
            "csrf_token": csrf_token,
            # Error-reporting panel: is Bugsnag live for this deployment, and
            # the outcome of the last "send test event" click (query flag).
            "error_reporting": {
                "configured": error_reporting_configured(),
                "release_stage": settings.ENVIRONMENT,
                "app_version": git_sha(),
                "status": request.query_params.get("error_reporting_test"),
            },
            "metrics": {
                "total_users": total_users,
                "new_users_today": new_users_today,
                "active_sessions": active_sessions,
                "missed_sessions_today": missed_sessions_today,
                "alerts_today": alerts_today,
                "active_subscriptions": active_subscriptions,
                "total_sessions": total_sessions,
            },
            "recent_sessions": recent_sessions,
        },
    )
    set_csrf_cookie(response, csrf_token)
    return response


@admin_router.post("/error-reporting-test")
async def admin_error_reporting_test(
    request: Request,
    current_admin: User = Depends(get_current_admin),
):
    """Send a deliberate test event so an operator can confirm reports reach
    Bugsnag for THIS deployment (release stage + version) — the post-deploy
    verification step in docs/deployment.md. Not a data mutation, so no audit
    row; CSRF-protected like every admin POST."""
    await validate_csrf_token(request)
    sent = report_error(
        ErrorReportingSmokeTestError(f"Admin smoke test (admin={current_admin.id})"),
        context="admin.error-reporting-test",
        metadata={"smoke": {"triggered_by": str(current_admin.id)}},
        severity="info",
    )
    return RedirectResponse(
        url=f"/admin/?error_reporting_test={'sent' if sent else 'unconfigured'}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Stuck-session actions (owner decisions 2026-07-19). A session never marked
# safe sits MISSED/ALERTED forever — its data is deliberately never
# auto-purged (potential evidence), so disposal/closure are HUMAN decisions:
# ---------------------------------------------------------------------------


@admin_router.post("/sessions/{session_id}/close-false-alarm")
async def admin_close_false_alarm(
    request: Request,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Close a stuck MISSED/ALERTED session as a confirmed false alarm.

    Sets CANCELLED — never COMPLETED, because the public all-clear card
    claims the owner "marked themselves safe", which an admin cannot
    truthfully assert; the CANCELLED page shows the neutral "no longer
    current" card instead. Resolves outstanding alerts, supersedes pending
    deliveries, and starts the normal retention clock. No all-clear
    broadcast is sent (same honesty reason)."""
    await validate_csrf_token(request)
    session = await db.get(Session, session_id)
    if session is not None and str(session.status) in (
        SessionStatus.MISSED.value,
        SessionStatus.ALERTED.value,
    ):
        session.status = SessionStatus.CANCELLED
        # Neutral session-end anchor (retention floor, purged-date fallback).
        # NEVER actual_return_time — that would claim the owner marked
        # themselves safe, which an admin cannot truthfully assert.
        session.cancelled_at = datetime.now(UTC)
        session.purge_after = datetime.now(UTC) + timedelta(
            days=settings.SESSION_DATA_RETENTION_DAYS
        )
        await db.commit()
        await crud_alert.resolve_session_alerts(db, session_id=session.id)
        await crud_nd.supersede(
            db, session_id=session.id, kind=NotificationKind.CIRCLE_ALERT
        )
        await crud_nd.supersede(
            db, session_id=session.id, kind=NotificationKind.CIRCLE_RENUDGE
        )
        await db.commit()
        await _write_audit_log(
            db,
            admin_user_id=current_admin.id,
            entity="session",
            action="close_false_alarm",
            entity_id=session.id,
            item=session,
        )
    return RedirectResponse(
        url=f"/admin/sessions/{session_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# Live statuses where marking safe on the owner's behalf makes sense (a
# terminal session has nothing to complete).
_LIVE_STATUSES = (
    SessionStatus.ACTIVE.value,
    SessionStatus.MISSED.value,
    SessionStatus.ALERTED.value,
)


@admin_router.get("/sessions/{session_id}/mark-safe", response_class=HTMLResponse)
async def admin_mark_safe_confirm(
    request: Request,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Step 1 of the double confirmation: consequence education (the
    all-clear broadcast messages real people) + the contrast with
    close-false-alarm, before any state changes."""
    session = await db.get(Session, session_id)
    if session is None or str(session.status) not in _LIVE_STATUSES:
        return RedirectResponse(
            url=f"/admin/sessions/{session_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    owner = await db.get(User, session.user_id)
    csrf_token = get_or_create_csrf_token(request)
    response = templates.TemplateResponse(
        request,
        "admin/mark_safe.html",
        {
            "request": request,
            "active_section": "sessions",
            "session_id": session.id,
            "owner_name": (owner.full_name or "this user") if owner else "this user",
            "csrf_token": csrf_token,
        },
    )
    set_csrf_cookie(response, csrf_token)
    return response


@admin_router.post("/sessions/{session_id}/mark-safe")
async def admin_mark_safe(
    request: Request,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Step 2: complete the session on the owner's behalf — via the SAME
    complete_session_with_all_clear() the mobile "I'm Safe" uses (alerts
    resolved, pending deliveries superseded, all-clear broadcast to the
    Circle). The verification acknowledgment is enforced HERE, not just by
    the form: a direct POST without `verified_safe` mutates nothing.
    Contrast: close-false-alarm stays for the unverified case (CANCELLED,
    no all-clear)."""
    await validate_csrf_token(request)
    form = await request.form()
    if form.get("verified_safe") != "yes":
        # No verification acknowledgment — back to the confirmation page,
        # nothing changed.
        return RedirectResponse(
            url=f"/admin/sessions/{session_id}/mark-safe",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    session = await db.get(Session, session_id)
    if session is not None and str(session.status) in _LIVE_STATUSES:
        owner = await db.get(User, session.user_id)
        if owner is not None:
            await complete_session_with_all_clear(db, session, owner)
            await _write_audit_log(
                db,
                admin_user_id=current_admin.id,
                entity="session",
                # Stored audit action value — kept as-is (it's data already
                # written to prod rows), even though the route/UI copy is
                # now "mark safe on their behalf" (2026-09-23 rename).
                action="checkin_on_behalf",
                entity_id=session.id,
                item=session,
            )
    return RedirectResponse(
        url=f"/admin/sessions/{session_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# ---------------------------------------------------------------------------
# Per-entry data management (owner decision 2026-07-19): scoped deletion of
# individual captured entries — one ping's coordinates, one ping's battery
# reading. Every mutation re-verifies the entity belongs to the
# session in the URL (a crafted cross-session ID is a silent no-op, never a
# cross-tenant delete) and writes an AdminAccessLog row in the same
# transaction as the change.
# ---------------------------------------------------------------------------


@admin_router.post("/sessions/{session_id}/updates/{update_id}/clear-location")
async def admin_clear_update_location(
    request: Request,
    session_id: UUID,
    update_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Null ONE ping's coordinates. A row can carry location AND battery, so
    scoped clearing (not row deletion) protects the other reading; the row is
    dropped once both are empty. The session's last-known pin re-derives from
    the latest remaining coord-bearing row everywhere (mobile, alert page)."""
    await validate_csrf_token(request)
    session = await db.get(Session, session_id)
    upd = await db.get(SessionUpdate, update_id)
    if session is not None and upd is not None and upd.session_id == session_id:
        upd.latitude = None
        upd.longitude = None
        if upd.battery_level is None and upd.battery_state is None:
            await db.delete(upd)
        await _write_audit_log(
            db,
            admin_user_id=current_admin.id,
            entity="session_update",
            action="clear_location_entry",
            entity_id=update_id,
            item=session,
        )
    return RedirectResponse(
        url=f"/admin/sessions/{session_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@admin_router.post("/sessions/{session_id}/updates/{update_id}/clear-battery")
async def admin_clear_update_battery(
    request: Request,
    session_id: UUID,
    update_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Null ONE ping's battery reading (counterpart of clear-location; the
    row is dropped once both readings are empty)."""
    await validate_csrf_token(request)
    session = await db.get(Session, session_id)
    upd = await db.get(SessionUpdate, update_id)
    if session is not None and upd is not None and upd.session_id == session_id:
        upd.battery_level = None
        upd.battery_state = None
        if upd.latitude is None and upd.longitude is None:
            await db.delete(upd)
        await _write_audit_log(
            db,
            admin_user_id=current_admin.id,
            entity="session_update",
            action="clear_battery_entry",
            entity_id=update_id,
            item=session,
        )
    return RedirectResponse(
        url=f"/admin/sessions/{session_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@admin_router.post("/sessions/{session_id}/purge-data")
async def admin_purge_session_data(
    request: Request,
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    """Immediately purge a session's captured data (photos + location trail).

    For confirmed false alarms that shouldn't wait out the retention clock.
    Refuses ACTIVE sessions — never destroy a live session's data. Uses the
    same purge_session_data() as the retention cleanup so the paths can't
    drift."""
    await validate_csrf_token(request)
    session = await db.get(Session, session_id)
    if session is not None and str(session.status) != SessionStatus.ACTIVE.value:
        await purge_session_data(db, session, BlobStorageService())
        await db.commit()
        await _write_audit_log(
            db,
            admin_user_id=current_admin.id,
            entity="session",
            action="purge_data",
            entity_id=session.id,
            item=session,
        )
    return RedirectResponse(
        url=f"/admin/sessions/{session_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
