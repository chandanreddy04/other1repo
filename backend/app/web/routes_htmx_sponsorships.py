"""
HTMX endpoints for the personalized sponsorship page.
Handles OTP verification for the sponsor, then returns a plan-selection form.
Related: routes_web.py (GET/POST /sponsorships/{share_code}), routes_htmx_referral.py
"""

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.db import get_db
from app.crud.phone_number import crud_phone_number
from app.services.otp import otp_service
from app.utils.phone import format_for_display, format_to_e164
from app.web.utils import get_phone_display_value

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/web/templates")
router = APIRouter(prefix="/htmx", tags=["web-htmx-sponsorships"])


@router.post("/sponsorships/{share_code}/request-otp", response_class=HTMLResponse)
async def sponsorship_request_otp(
    request: Request,
    share_code: str,
    phone_number: str = Form(...),
    full_phone_number: str = Form(None),
    is_resend: bool = Form(False),
    force_resend: bool = Form(False),
    keep_otp_visible: bool = Form(False),
    current_phone: str = Form(None),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Send OTP to the sponsor's phone number."""
    phone_to_format = full_phone_number if full_phone_number else phone_number
    formatted_phone = format_to_e164(phone_to_format)
    if not formatted_phone:
        return templates.TemplateResponse(
            request,
            "fragments/sponsorship_auth_form.html",
            {
                "request": request,
                "share_code": share_code,
                "phone_value": phone_to_format,
                "error_message": "Please enter a valid phone number",
                "show_otp": False,
            },
        )

    # Same phone re-submitted — just restore OTP section without re-sending
    if current_phone and current_phone == formatted_phone:
        resend_wait_seconds = await otp_service.get_resend_wait_seconds(
            db, formatted_phone
        )
        return templates.TemplateResponse(
            request,
            "fragments/sponsorship_auth_form.html",
            {
                "request": request,
                "share_code": share_code,
                "phone_number": formatted_phone,
                "phone_value": get_phone_display_value(formatted_phone),
                "display_phone": format_for_display(formatted_phone),
                "show_otp": True,
                "resend_wait_seconds": resend_wait_seconds,
            },
        )

    success, message = await otp_service.send_otp(
        db, formatted_phone, force_resend=(is_resend or force_resend)
    )
    resend_wait_seconds = await otp_service.get_resend_wait_seconds(db, formatted_phone)
    display_phone = format_for_display(formatted_phone)

    if not success:
        return templates.TemplateResponse(
            request,
            "fragments/sponsorship_auth_form.html",
            {
                "request": request,
                "share_code": share_code,
                "phone_number": formatted_phone,
                "phone_value": get_phone_display_value(formatted_phone),
                "display_phone": display_phone,
                "error_message": message,
                "show_otp": keep_otp_visible or is_resend,
                "resend_wait_seconds": resend_wait_seconds,
            },
        )

    return templates.TemplateResponse(
        request,
        "fragments/sponsorship_auth_form.html",
        {
            "request": request,
            "share_code": share_code,
            "phone_number": formatted_phone,
            "phone_value": get_phone_display_value(formatted_phone),
            "display_phone": display_phone,
            "show_otp": True,
            "resend_wait_seconds": resend_wait_seconds,
        },
    )


@router.post("/sponsorships/{share_code}/verify-otp", response_class=HTMLResponse)
async def sponsorship_verify_otp(
    request: Request,
    share_code: str,
    phone_number: str = Form(...),
    otp_code: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """Verify OTP and swap in plan-selection form."""
    # Validate before anything is echoed back: the failure fragment puts the
    # phone into hidden inputs and hx-vals JSON, so only an E164 value that
    # passed the same check request-otp uses may be rendered there.
    formatted_phone = format_to_e164(phone_number)
    if not formatted_phone:
        return templates.TemplateResponse(
            request,
            "fragments/sponsorship_auth_form.html",
            {
                "request": request,
                "share_code": share_code,
                "error_message": "Please enter a valid phone number",
                "show_otp": False,
            },
        )

    success, message = await otp_service.verify_otp(db, formatted_phone, otp_code)

    if not success:
        return templates.TemplateResponse(
            request,
            "fragments/sponsorship_auth_form.html",
            {
                "request": request,
                "share_code": share_code,
                "phone_number": formatted_phone,
                "phone_value": get_phone_display_value(formatted_phone),
                "display_phone": format_for_display(formatted_phone),
                "error_message": message,
                "show_otp": True,
                "resend_wait_seconds": 0,
            },
        )

    phone_rec, _ = await crud_phone_number.get_or_create(db, number=formatted_phone)
    if not phone_rec.verified:
        await crud_phone_number.mark_verified(db, phone=phone_rec)

    return templates.TemplateResponse(
        request,
        "fragments/sponsorship_plan_form.html",
        {
            "request": request,
            "share_code": share_code,
            "gifter_phone": formatted_phone,
        },
    )
