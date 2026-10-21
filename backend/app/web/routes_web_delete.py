"""Web routes for cold-start account deletion.

The flow is the public, sign-in-less mirror of the mobile Danger Zone:
mandated by Google Play's User Data policy (a web-accessible deletion
path) and useful for everyone. Four GET/POST steps, full page reloads
(no HTMX) — this is a once-per-account flow, latency isn't the priority,
state simplicity is.

  1. GET  /account/delete               → phone form
  2. POST /account/delete/codes         → creates an OTP code, render
                                          OTP form
  3. POST /account/delete/verifications → creates a verification of the
                                          code, sets short-lived
                                          deletion-token cookie, render
                                          the personalized confirmation
                                          + typed gate
  4. POST /account/delete/confirmations → creates a confirmation: check
                                          cookie + typed gate, run
                                          delete_user_account, render the
                                          success page; cookie is cleared

Each POST is named after the resource it creates (a code, a
verification, a confirmation) rather than a verb, per the REST-shaped
path vocabulary (owner decision 2026-09-23) — these are still RPC-ish
state-machine stages, not real independently-addressable resources, but
naming them as creations keeps the routes noun-shaped.

The deletion token is a 10-minute JWT (`type="delete"`) carrying the
user_id discovered at OTP verify. It's the only auth artifact in this
flow — no access tokens are issued. Stealing the cookie within its 10
minutes would let an attacker delete that one user; the mobile/in-app
flow is a higher-value target than this, and 10 minutes is a tight
replay window per docs/account-deletion-plan.md.

Related:
- app/services/account_deletion.py (orchestrator + mint/decode token)
- app/web/templates/web_delete_account.html (renders all four stages)
"""

import logging

from fastapi import APIRouter, Cookie, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.db import get_db
from app.crud import crud_user
from app.services import account_deletion
from app.services.account_deletion import (
    DELETION_TOKEN_TTL_MINUTES,
    decode_deletion_token,
    mint_deletion_token,
)
from app.services.otp import otp_service
from app.utils.phone import format_for_display, format_to_e164

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/web/templates")
router = APIRouter(tags=["web-delete"])

DELETION_COOKIE_NAME = "mih_deletion_token"
CONFIRM_PHRASE = "delete"


def _render(
    request: Request,
    stage: str,
    error: str | None = None,
    **ctx: object,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "web_delete_account.html",
        {"request": request, "stage": stage, "error": error, **ctx},
    )


@router.get("/account/delete", response_class=HTMLResponse)
async def delete_account_phone_form(request: Request) -> HTMLResponse:
    return _render(request, stage="phone")


@router.post("/account/delete/codes", response_class=HTMLResponse)
async def delete_account_send_otp(
    request: Request,
    phone_number: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    e164 = format_to_e164(phone_number)
    if not e164:
        return _render(
            request,
            stage="phone",
            phone_value=phone_number,
            error="Please enter a valid US phone number.",
        )

    user = await crud_user.get_by_phone(db, phone_number=e164)
    if user is None:
        # Don't reveal whether the number is registered — same UX as
        # password resets on most services. We just render the OTP
        # form; if they didn't actually receive an OTP they'll learn
        # at the verify step (and that page tells them no account
        # exists, which is fine post-OTP failure but not pre).
        return _render(
            request,
            stage="otp",
            phone_e164=e164,
            display_phone=format_for_display(e164),
        )

    await otp_service.send_otp(db, e164)
    return _render(
        request,
        stage="otp",
        phone_e164=e164,
        display_phone=format_for_display(e164),
    )


@router.post("/account/delete/verifications", response_class=HTMLResponse)
async def delete_account_verify_otp(
    request: Request,
    phone_number: str = Form(...),
    otp_code: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    e164 = format_to_e164(phone_number)
    if not e164:
        return _render(
            request,
            stage="phone",
            error="Please re-enter your phone number.",
        )

    ok, message = await otp_service.verify_otp(db, e164, otp_code)
    if not ok:
        return _render(
            request,
            stage="otp",
            phone_e164=e164,
            display_phone=format_for_display(e164),
            error=message,
        )

    user = await crud_user.get_by_phone(db, phone_number=e164)
    if user is None:
        return _render(
            request,
            stage="otp",
            phone_e164=e164,
            display_phone=format_for_display(e164),
            error="No account exists for this phone number.",
        )

    token = mint_deletion_token(user.id)
    response = _render(
        request,
        stage="confirm",
        display_phone=format_for_display(e164),
        full_name=user.full_name,
        grace_days=account_deletion.DELETION_GRACE_DAYS,
    )
    response.set_cookie(
        DELETION_COOKIE_NAME,
        token,
        max_age=DELETION_TOKEN_TTL_MINUTES * 60,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.post("/account/delete/confirmations", response_class=HTMLResponse)
async def delete_account_confirm(
    request: Request,
    confirm_phrase: str = Form(...),
    deletion_token: str | None = Cookie(None, alias=DELETION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if deletion_token is None:
        return _render(
            request,
            stage="phone",
            error="Your session expired. Please start over.",
        )

    user_id = decode_deletion_token(deletion_token)
    if user_id is None:
        return _render(
            request,
            stage="phone",
            error="Your session expired. Please start over.",
        )

    if confirm_phrase.strip().lower() != CONFIRM_PHRASE:
        # Re-render confirm stage; cookie still valid, just ask again.
        user = await crud_user.get(db, id=user_id)
        return _render(
            request,
            stage="confirm",
            full_name=user.full_name if user else None,
            grace_days=account_deletion.DELETION_GRACE_DAYS,
            error=f'Please type "{CONFIRM_PHRASE}" to confirm.',
        )

    user = await crud_user.get(db, id=user_id)
    if user is None:
        # Vanishingly rare: token references a user that was removed
        # between verify and confirm. Treat as success either way —
        # there's nothing left to delete.
        response = _render(request, stage="success")
        response.delete_cookie(DELETION_COOKIE_NAME)
        return response

    deleted_at = await account_deletion.delete_user_account(db, user)
    response = _render(
        request,
        stage="success",
        scheduled_purge_at=account_deletion.scheduled_purge_at(deleted_at),
        grace_days=account_deletion.DELETION_GRACE_DAYS,
    )
    response.delete_cookie(DELETION_COOKIE_NAME)
    return response
