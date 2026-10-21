"""Web routes for the phone-keyed sponsorship-management page.

Independent of deletion. Useful today for sponsors who paid via Stripe
checkout and have no other way to view, cancel, or update card details
on their subscriptions — and useful AFTER deletion for users who chose
to keep sponsoring someone past their own account being gone.

Flow (full page reloads, no HTMX):

  1. GET  /sponsorships              → phone form
  2. POST /sponsorships/sign-in-links → look up user by phone; if found,
                                       SMS a magic link carrying a
                                       one-time sign-in token; either
                                       way render "check your texts"
                                       (don't oracle whether the phone
                                       is registered)
  3. GET  /sponsorships/portal/{token} → read-only check that the token
                                       exists, is unexpired and unused;
                                       render a one-button "Open billing
                                       portal" page. Does NOT consume:
                                       link previewers (iMessage, Slack…)
                                       GET the URL on their own, and must
                                       not burn the one-time link or open
                                       a Stripe session. The SMS actually
                                       carries the short link
                                       {SHORT_DOMAIN}/s/p/{token}, which
                                       302s here.
     POST /sponsorships/portal/{token} → the button: consume the token,
                                       look up the Stripe Customer,
                                       create a billing portal session,
                                       303 to Stripe (on a Stripe error:
                                       release the token and re-render
                                       the button with a retry message).
     GET  /sponsorships/portal        → a token-less (truncated) link:
                                       the "link has expired" phone stage.
  4. GET  /sponsorships?status=saved → return_url from Stripe. Renders
                                       a "Changes saved" confirmation
                                       as the `saved` state of the
                                       phone-form page.

The magic link IS the auth: the SMS proves phone ownership and the token
proves the link came from us. No persistent session is created. The
token is single-use: `consume()` atomically stamps `used_at` before the
Stripe call, so replaying a used or expired link renders the same "link
has expired" state as an unknown token; if the Stripe portal session then
fails, `release()` clears `used_at` so the same link can be retried (until
its original expiry) rather than being burnt by a provider blip.

Related:
- app/models/sponsorship_sign_in_token.py, app/crud/sponsorship_sign_in_token.py
  (the one-time token this flow mints/consumes)
- app/web/short_links.py (the /s/p/{token} short link that 302s to
  /sponsorships/portal/{token})
- app/services/stripe_service.py (create_portal_session)
- docs/account-deletion-plan.md (Phase 7.5)
- app/main.py include_router ordering: this router is included BEFORE
  routes_web.py's web_router, so its literal /sponsorships, /sponsorships
  /sign-in-links routes aren't shadowed by web_router's
  GET /sponsorships/{share_code} — including the token-less
  GET /sponsorships/portal, which would otherwise render the share-code
  404. /sponsorships/portal/{token} has an extra path segment so it can't
  collide with {share_code} either way.
"""

import logging

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.crud import crud_user
from app.crud.sponsorship_sign_in_token import crud_sponsorship_sign_in_token
from app.models.user import is_stripe_customer_pending
from app.services import sms_opt_out, stripe_service
from app.services.account_deletion import STRIPE_CUSTOMER_PURGED_PREFIX
from app.utils.phone import format_for_display, format_to_e164, phone_tag

logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory="app/web/templates")
router = APIRouter(tags=["web-sponsorships"])


def _render(
    request: Request,
    stage: str,
    error: str | None = None,
    **ctx: object,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "web_sponsorships.html",
        {"request": request, "stage": stage, "error": error, **ctx},
    )


def _magic_link_url(token: str) -> str:
    return f"{settings.SHORT_DOMAIN}/s/p/{token}"


def _stripe_customer_usable(stripe_customer_id: str | None) -> bool:
    if not stripe_customer_id:
        return False
    if is_stripe_customer_pending(stripe_customer_id):
        return False
    return not stripe_customer_id.startswith(STRIPE_CUSTOMER_PURGED_PREFIX)


_LINK_EXPIRED = "That link has expired. Please request a new one."


def _render_link_expired(request: Request) -> HTMLResponse:
    """Unknown, expired, used and token-less links all get this same phone
    stage — the response never distinguishes those cases."""
    return _render(request, stage="phone", error=_LINK_EXPIRED)


@router.get("/sponsorships", response_class=HTMLResponse)
async def sponsorships_phone_form(
    request: Request,
    status_: str | None = Query(default=None, alias="status"),
) -> HTMLResponse:
    if status_ == "saved":
        return _render(request, stage="saved")
    return _render(request, stage="phone")


# POST /sponsorships/sign-in-links is a controller action (sends a
# fire-and-forget magic-link SMS), not a resource create — an accepted
# REST deviation; see ALLOWED_ACTION_ROUTES in test_rest_conventions.py.
@router.post("/sponsorships/sign-in-links", response_class=HTMLResponse)
async def sponsorships_request_link(
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
    if user is not None and _stripe_customer_usable(user.stripe_customer_id):
        sign_in_token = await crud_sponsorship_sign_in_token.create_for_phone(
            db, phone_number_id=user.phone_number_id
        )
        link = _magic_link_url(sign_in_token.token)
        message = (
            "Manage your Made It Home sponsorships: "
            + link
            + " (link expires in 10 minutes)"
        )
        await sms_opt_out.gated_send_sms(db, to_phone=e164, message=message)

    # Same response whether or not we sent — don't oracle account/customer
    # presence pre-click.
    return _render(
        request,
        stage="sent",
        display_phone=format_for_display(e164),
    )


# Registered before GET /sponsorships/portal/{token} for readability only —
# the extra segment already keeps them apart. What matters is that this
# router is included before web_router (main.py), so this literal path wins
# over GET /sponsorships/{share_code}.
@router.get("/sponsorships/portal", response_class=HTMLResponse)
async def sponsorships_portal_without_token(request: Request) -> HTMLResponse:
    return _render_link_expired(request)


@router.get("/sponsorships/portal/{token}", response_class=HTMLResponse)
async def sponsorships_portal_landing(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    # Read-only: a GET never consumes the token (link previewers fetch it).
    # The page's button POSTs back to this same URL, which consumes.
    if not await crud_sponsorship_sign_in_token.is_redeemable(db, token=token):
        return _render_link_expired(request)
    return _render(request, stage="open")


# POST redeems the one-time token (the state change a GET must not make) and
# opens a Stripe portal session.
@router.post("/sponsorships/portal/{token}", response_model=None)
async def sponsorships_open_portal(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse | RedirectResponse:
    # An unknown, expired, or already-used token gets the same "expired
    # link" phone-stage render — consume() can't (and shouldn't)
    # distinguish those cases in its response.
    phone = await crud_sponsorship_sign_in_token.consume(db, token=token)
    if phone is None:
        return _render_link_expired(request)
    phone_e164 = phone.number

    user = await crud_user.get_by_phone(db, phone_number=phone_e164)
    if user is None or not _stripe_customer_usable(user.stripe_customer_id):
        return _render(
            request,
            stage="not_found",
            display_phone=format_for_display(phone_e164),
        )

    return_url = f"{settings.APP_DOMAIN}/sponsorships?status=saved"
    try:
        portal = stripe_service.create_portal_session(
            user.stripe_customer_id, return_url=return_url
        )
    except Exception:
        logger.exception(
            "stripe_portal_open_failed",
            extra={"phone_tag": phone_tag(phone_e164)},
        )
        # The token was consumed up front (atomically — so two concurrent
        # clicks can't both open a portal), but a Stripe failure must not
        # burn the sponsor's one link: hand it back so "try again in a
        # moment" is true with the same link, until its original expiry.
        await crud_sponsorship_sign_in_token.release(db, token=token)
        # Re-render the button (it POSTs back to this same URL) so the retry
        # is one tap, not another trip through the SMS link.
        return _render(
            request,
            stage="open",
            error="We couldn't open the billing portal. Please try again in a moment.",
        )

    # 303: the browser follows the POST's redirect with a GET to Stripe.
    return RedirectResponse(url=portal.url, status_code=status.HTTP_303_SEE_OTHER)
