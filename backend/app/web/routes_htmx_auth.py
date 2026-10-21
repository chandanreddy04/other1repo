"""
HTMX endpoints for main login authentication flow.
Returns HTML fragments for OTP request and verification.
"""

import json
import logging
from datetime import timedelta
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import escape  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import create_access_token
from app.crud.phone_number import crud_phone_number
from app.crud.user import crud_user
from app.schemas.user import UserCreate
from app.services import sms_opt_out
from app.services.otp import otp_service
from app.utils.phone import format_for_display, format_to_e164
from app.web.utils import get_phone_display_value, safe_next_path, set_auth_cookie

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/web/templates")
router = APIRouter(prefix="/htmx", tags=["web-htmx-auth"])


@router.get("/auth/phone-form", response_class=HTMLResponse)
async def get_phone_form(
    request: Request,
    allow_immediate: bool = False,
    phone: str | None = None,
):
    """Return the phone number entry form"""
    phone_value = get_phone_display_value(phone) if phone else ""

    return templates.TemplateResponse(
        request,
        "fragments/auth_form.html",
        {
            "request": request,
            "allow_immediate": allow_immediate,
            "phone_value": phone_value,
            "show_otp": False,
        },
    )


@router.post("/auth/request-otp", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def request_otp(
    request: Request,
    phone_number: str = Form(...),
    full_phone_number: str = Form(None),  # Added to handle the JS-created field
    next_url: str | None = Form(None),
    is_resend: bool = Form(False),
    force_resend: bool = Form(False),
    keep_otp_visible: bool = Form(False),
    current_phone: str = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Request OTP for authentication"""
    # Redirect-safety rule (.claude/rules/security.md): next_url is echoed
    # into auth_form.html (hidden input + hx-vals JSON) — validate it once.
    next_url = safe_next_path(next_url)

    # Use full_phone_number if provided (from JS), otherwise use phone_number
    phone_to_format = full_phone_number if full_phone_number else phone_number

    # Format phone number
    formatted_phone = format_to_e164(phone_to_format)
    if not formatted_phone:
        # Return the unified form with error
        return templates.TemplateResponse(
            request,
            "fragments/auth_form.html",
            {
                "request": request,
                "phone_value": phone_to_format,
                "error_message": "Please enter a valid phone number",
                "show_otp": False,
            },
        )

    # If current_phone is provided and matches the new phone, just show OTP form again
    if current_phone and current_phone == formatted_phone:
        resend_wait_seconds = await otp_service.get_resend_wait_seconds(
            db, formatted_phone
        )
        display_phone = format_for_display(formatted_phone)
        return templates.TemplateResponse(
            request,
            "fragments/auth_form.html",
            {
                "request": request,
                "phone_number": formatted_phone,
                "phone_value": get_phone_display_value(formatted_phone),
                "display_phone": display_phone,
                "next_url": next_url,
                "show_otp": True,
                "resend_wait_seconds": resend_wait_seconds,
            },
        )

    # Refuse to send to a number that texted STOP — same gate as the JSON API.
    if await sms_opt_out.is_opted_out(db, formatted_phone):
        return templates.TemplateResponse(
            request,
            "fragments/auth_form.html",
            {
                "request": request,
                "phone_value": get_phone_display_value(formatted_phone),
                "show_otp": False,
                "error_message": (
                    "This number is unsubscribed from our texts. Reply START to "
                    f"{settings.TWILIO_PHONE_NUMBER} from this phone to re-enable them."
                ),
            },
        )

    # Send OTP (use force_resend only for explicit resend)
    success, message = await otp_service.send_otp(
        db, formatted_phone, force_resend=(is_resend or force_resend)
    )

    # Calculate resend wait time (only for active OTPs)
    resend_wait_seconds = await otp_service.get_resend_wait_seconds(db, formatted_phone)
    display_phone = format_for_display(formatted_phone)

    if not success:
        # Return unified form with error, keeping OTP section visible if it was a resend
        return templates.TemplateResponse(
            request,
            "fragments/auth_form.html",
            {
                "request": request,
                "phone_number": formatted_phone,
                "phone_value": get_phone_display_value(formatted_phone),
                "display_phone": display_phone,
                "next_url": next_url,
                "error_message": message,
                "show_otp": keep_otp_visible or is_resend,
                "resend_wait_seconds": resend_wait_seconds,
            },
        )

    # Return unified form with OTP section visible
    return templates.TemplateResponse(
        request,
        "fragments/auth_form.html",
        {
            "request": request,
            "phone_number": formatted_phone,
            "phone_value": get_phone_display_value(formatted_phone),
            "display_phone": display_phone,
            "next_url": next_url,
            "show_otp": True,
            "resend_wait_seconds": resend_wait_seconds,
        },
    )


@router.post("/auth/verify-otp", response_class=HTMLResponse)
async def verify_otp(
    request: Request,
    phone_number: str = Form(...),
    otp_code: str = Form(...),
    next_url: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Verify OTP and authenticate user"""
    # Redirect-safety rule (.claude/rules/security.md): validate once, up
    # front — next_url is echoed into the re-rendered forms below (incl. the
    # hx-vals JSON in fragments/auth_form.html) and into the JS redirect.
    next_url = safe_next_path(next_url)

    # Verify OTP
    success, message = await otp_service.verify_otp(db, phone_number, otp_code)

    if not success:
        display_phone = format_for_display(phone_number)
        return templates.TemplateResponse(
            request,
            "fragments/auth_form.html",
            {
                "request": request,
                "phone_number": phone_number,
                "phone_value": get_phone_display_value(phone_number),
                "display_phone": display_phone,
                "next_url": next_url,
                "error_message": message,
                "show_otp": True,
                "resend_wait_seconds": 0,
            },
        )

    # Format phone number to E164
    formatted_phone = format_to_e164(phone_number)
    if not formatted_phone:
        return templates.TemplateResponse(
            request,
            "fragments/otp_verification.html",
            {
                "request": request,
                "phone_number": phone_number,
                "next_url": next_url,
                "error_message": "Invalid phone number format",
                "show_resend": True,
            },
        )

    # Mark phone number as verified
    phone_rec, _ = await crud_phone_number.get_or_create(db, number=formatted_phone)
    if not phone_rec.verified:
        await crud_phone_number.mark_verified(db, phone=phone_rec)

    # Get or create user
    try:
        user = await crud_user.get_by_phone(db, phone_number=formatted_phone)
        if not user:
            # Create new user with just phone number
            user_create = UserCreate(phone_number=formatted_phone, full_name=None)
            user = await crud_user.create(db, obj_in=user_create)
    except Exception as e:
        logger.exception("Error creating/fetching user")
        return templates.TemplateResponse(
            request,
            "fragments/otp_verification.html",
            {
                "request": request,
                "phone_number": phone_number,
                "next_url": next_url,
                "error_message": f"An error occurred during verification: {e!s}",
                "show_resend": True,
            },
        )

    # Create access token
    # The web/admin flow is cookie-based with no refresh, so mint a token whose
    # lifetime matches the auth cookie (set_auth_cookie's 7-day max_age) instead
    # of the 30-min mobile default — otherwise the JWT expired long before the
    # cookie, logging web users out mid-session and leaving a stale cookie.
    access_token = create_access_token(
        user.id, expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )

    # next_url was validated by safe_next_path at the top of the handler.
    redirect_url = next_url or "/alerts"

    # Name gate (owner decision 2026-09-23): CLAUDE.md requires a name for
    # every new user, but this handler creates one with full_name=None
    # (above) and nothing on the web ever asked for it until GET /account.
    # Send a nameless user there first, carrying the real target as ?next=
    # so they land where they were headed once they've named themselves.
    # A target that already IS /account (the logged-out /account?next=…
    # round trip) is used as-is — wrapping it again made the user save twice.
    if not user.full_name and urlsplit(redirect_url).path != "/account":
        redirect_url = f"/account?next={quote(redirect_url)}"

    safe_url = json.dumps(redirect_url)

    response = HTMLResponse(
        content=f"""
        <div class="text-center">
            <div class="alert alert-success mb-md">
                Successfully verified! Redirecting...
            </div>
            <div class="loading-spinner"></div>
        </div>
        <script>
            setTimeout(() => {{
                window.location.replace({safe_url});
            }}, 1000);
        </script>
        """
    )
    set_auth_cookie(response, access_token)
    return response
