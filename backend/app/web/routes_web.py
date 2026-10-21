"""
Web interface routes for Made It Home.
"""

import logging
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Form,
    Query,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps.auth import get_current_user_from_cookie, get_current_user_optional
from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.crud.alert import crud_alert, stale_incident_cutoff
from app.crud.circle_of_trust import crud_circle_of_trust
from app.crud.user import crud_user
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import ContactStatus
from app.models.session import Session as SessionModel
from app.models.session import SessionStatus
from app.models.user import User
from app.schemas.user import UserUpdate
from app.services import circle_invitations
from app.services.referral import referral_service
from app.services.session_tasks import _format_local_datetime
from app.utils.phone import format_for_display, format_to_e164
from app.web.short_links import NESTED_SHORT_LINKS, SHORT_LINKS
from app.web.utils import clear_auth_cookie, safe_next_path, store_redirect_url

templates = Jinja2Templates(directory="app/web/templates")
# Marketing pages live only on the separate marketing-site repo (owner
# decision 2026-09-23). Every template rendered through this environment
# can reach `{{ marketing_origin }}` (e.g. the login header logo link,
# referral/sponsorship "back to home" links) without each route passing
# it in its own context.
templates.env.globals["marketing_origin"] = settings.MARKETING_ORIGIN
web_router = APIRouter(tags=["web"])
logger = logging.getLogger(__name__)


@web_router.get("/")
async def marketing_redirect():
    """Marketing lives only on the marketing-site repo (owner decision
    2026-09-23). This app backend serves no marketing page."""
    return RedirectResponse(
        url=settings.MARKETING_ORIGIN, status_code=status.HTTP_301_MOVED_PERMANENTLY
    )


@web_router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    inviter: str | None = None,
    next: str | None = None,
    current_user: User | None = Depends(get_current_user_from_cookie),
):
    """Login page - redirects to the Circle member's alerts if already
    authenticated (owner decision 2026-09-23: /alerts, not /dashboard —
    the web dashboard was removed)."""
    # Redirect-safety rule (.claude/rules/security.md): internal paths only.
    safe_next = safe_next_path(next)
    if current_user:
        return RedirectResponse(
            url=safe_next or "/alerts", status_code=status.HTTP_302_FOUND
        )

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "inviter_name": inviter,
            "next_url": safe_next,
            "current_year": datetime.now().year,
        },
    )


def _require_name(
    current_user: User | None, request: Request
) -> RedirectResponse | None:
    """Name gate (owner decision 2026-09-23): CLAUDE.md requires a name for
    every user, but the web sign-up (routes_htmx_auth.py verify_otp,
    routes_htmx_referral.py referral_verify_otp) creates the user with
    full_name=None and nothing on the web ever asked for it until now.

    Called at the top of every cookie-auth Circle-member page (GET /alerts,
    GET /circles, GET /circles/{code}) — NOT GET /alerts/{id}, which is
    public/tokenised and has no current_user. Returns a redirect to
    GET /account with ?next=<the page the caller was headed to> when the
    viewer is logged in but nameless; None otherwise (not logged in, or
    already has a name), so callers can `if (gate := _require_name(...)):
    return gate` without disturbing their own login-redirect logic.
    """
    if not current_user or current_user.full_name:
        return None
    next_target = request.url.path
    if request.url.query:
        next_target = f"{next_target}?{request.url.query}"
    return RedirectResponse(
        url=f"/account?next={quote(next_target)}", status_code=status.HTTP_302_FOUND
    )


def _login_redirect_to_account(safe_next: str | None) -> RedirectResponse:
    """Logged-out GET/POST /account → /login, carrying /account (and its own
    already-validated ?next=) as the login's next, so the full chain
    login → /account → original target survives. Double-encoded on purpose:
    the inner `next` is quoted inside /account's URL, and that whole URL is
    quoted again as /login's `next`; each hop decodes exactly one layer."""
    login_next = f"/account?next={quote(safe_next)}" if safe_next else "/account"
    return RedirectResponse(
        url=f"/login?next={quote(login_next)}", status_code=status.HTTP_302_FOUND
    )


@web_router.get("/account", response_class=HTMLResponse)
async def account_page(
    request: Request,
    next: str | None = None,
    saved: str | None = None,
    current_user: User | None = Depends(get_current_user_from_cookie),
):
    """Account hub (renamed from GET /profile, owner decision 2026-09-23):
    'Account' is the hub, 'profile' is the name/photo shown to contacts."""

    safe_next = safe_next_path(next)
    if not current_user:
        return _login_redirect_to_account(safe_next)

    formatted_phone = format_for_display(current_user.phone_number)

    return templates.TemplateResponse(
        request,
        "account.html",
        {
            "request": request,
            "current_user": current_user,
            "formatted_phone": formatted_phone,
            "next_url": safe_next,
            "saved": saved == "1",
        },
    )


@web_router.post("/account", response_class=HTMLResponse)
async def account_update(
    request: Request,
    full_name: str = Form(...),
    next: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_from_cookie),
):
    """Save the Account name — plain form + PRG (moved from the deleted
    profile-update htmx handler, owner decision 2026-09-23: no aliases
    shipped, so that route is deleted rather than kept alongside this
    one). Validation matches the deleted handler: strip, required,
    length (schemas.user.UserUpdate). A rejected name is user input, not
    a defect — it re-renders the form with a friendly message and is NOT
    reported; only the DB update sits in the broad, reported try.
    """
    safe_next = safe_next_path(next)
    if not current_user:
        return _login_redirect_to_account(safe_next)

    formatted_phone = format_for_display(current_user.phone_number)

    def _rerender(error: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "account.html",
            {
                "request": request,
                "current_user": current_user,
                "formatted_phone": formatted_phone,
                "next_url": safe_next,
                "name_value": full_name,
                "error": error,
            },
        )

    try:
        user_update = UserUpdate(full_name=full_name.strip())
    except ValidationError:
        # benign: user input — an empty/whitespace or over-long name.
        return _rerender("Please enter your name (up to 100 characters).")

    try:
        await crud_user.update(db, db_obj=current_user, obj_in=user_update)
    except Exception:
        logger.exception("Error updating account name")
        return _rerender("Failed to update profile. Please try again.")

    redirect_url = safe_next or "/account?saved=1"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@web_router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """List every alert sent to this Circle member, newest first.

    LIST ONLY (owner decision 2026-09-23): a row shows who/what/when/status
    and links to GET /alerts/{alert_id} — the single place details (location,
    destination, contact, photo) render. Replaces the old inline-detail page,
    which read session fields directly (bypassing the circle-viewer
    snapshot — leaking coordinates when location sharing was off, raw phone,
    raw S3 photo URL) and compared alert_type/status against uppercase
    strings that never matched the stored lowercase enum values.
    """
    current_user = await get_current_user_optional(db, access_token)

    if not current_user:
        # Redirect to login
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    if gate := _require_name(current_user, request):
        return gate

    alerts = await crud_alert.get_user_alerts(db, user_id=current_user.id, limit=50)
    unack_alerts = await crud_alert.get_unacknowledged_alerts(
        db, user_id=current_user.id
    )

    now = datetime.now(UTC)
    rows = [_alert_list_row(alert, now=now) for alert in alerts]

    return templates.TemplateResponse(
        request,
        "alerts.html",
        {
            "request": request,
            "current_user": current_user,
            "rows": rows,
            "unack_count": len(unack_alerts),
        },
    )


async def _circle_member_rows(
    db: AsyncSession, current_user: User
) -> tuple[list[dict], list[dict]]:
    """The viewer's pending Circle invitations and ACTIVE memberships, each
    paired with its inviter — the page's row builder for GET /circles.

    Inviters are loaded in ONE query (get_multi_by_ids) and passed to the
    template explicitly: `CircleOfTrustMember.user` is a lazy relationship,
    so touching it in a template on a fresh request session raises
    MissingGreenlet (a 500 for anyone with a pending invite, pinned by
    tests/test_web_circles.py). Memberships are matched
    by the viewer's phone and filtered to ACTIVE — never the circles the
    viewer OWNS (get_user_contacts).
    """
    pending_invitations = await crud_circle_of_trust.get_pending_invitations_for_user(
        db, user_id=current_user.id
    )
    memberships = await crud_circle_of_trust.get_memberships_for_user(
        db, user_id=current_user.id
    )
    active_memberships = [m for m in memberships if m.status == ContactStatus.ACTIVE]

    inviter_ids = {inv.user_id for inv in pending_invitations} | {
        m.user_id for m in active_memberships
    }
    inviters = await crud_user.get_multi_by_ids(db, ids=list(inviter_ids))
    inviters_by_id = {inviter.id: inviter for inviter in inviters}

    enriched_invitations = [
        {"invitation": inv, "inviter": inviters_by_id.get(inv.user_id)}
        for inv in pending_invitations
    ]
    enriched_memberships = [
        {"membership": m, "inviter": inviters_by_id.get(m.user_id)}
        for m in active_memberships
    ]
    return enriched_invitations, enriched_memberships


@web_router.get("/circles", response_class=HTMLResponse)
async def circles_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    access_token: str | None = Cookie(None),
):
    """The signed-in Circle member's page (renamed from /invitations,
    owner decision 2026-09-23): pending invitations addressed to them, and
    the circles they're an ACTIVE member of.

    NOT the circles they own — get_user_contacts (used by the old "active
    circles" section) returns the inviter's OWN circle, which was the
    wrong data for a Circle-member page (crud/circle_of_trust.py:31-39).
    Membership rows come from get_memberships_for_user, which matches by
    the viewer's phone and returns PENDING+ACTIVE; filtered here to ACTIVE
    since pending ones are already shown in the invitations section above.
    """

    current_user = await get_current_user_optional(db, access_token)

    if not current_user:
        return RedirectResponse(
            url="/login?next=/circles", status_code=status.HTTP_302_FOUND
        )
    if gate := _require_name(current_user, request):
        return gate

    enriched_invitations, enriched_memberships = await _circle_member_rows(
        db, current_user
    )

    return templates.TemplateResponse(
        request,
        "circles.html",
        {
            "request": request,
            "current_user": current_user,
            "pending_invitations": enriched_invitations,
            "memberships": enriched_memberships,
        },
    )


def _first_name(user: User, *, default: str) -> str:
    """First word of the user's full name, or `default` when unnamed."""
    parts = (user.full_name or "").split()
    return parts[0] if parts else default


@web_router.get("/sponsorships/new", response_class=HTMLResponse)
async def sponsorships_new_page(
    request: Request,
    phone: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    back: str | None = None,
):
    """Sponsor-a-subscription entry page (generic, no recipient known yet).

    Accepts ?phone={e164} (direct link) to prefill the recipient field.
    Also renders the success/canceled states after Stripe redirects back
    here (?status=success|canceled). The success state is deliberately
    generic: no phone or name rides in the Stripe-stored success URL
    (phone numbers are PII — security.md), so none is echoed here.
    """
    if status_ == "success":
        return templates.TemplateResponse(
            request,
            "sponsorship.html",
            {
                "request": request,
                "state": "success",
                "current_year": datetime.now().year,
            },
        )
    if status_ == "canceled":
        return templates.TemplateResponse(
            request,
            "sponsorship.html",
            {
                "request": request,
                "state": "canceled",
                "back_url": safe_next_path(back, default="/sponsorships/new"),
                "current_year": datetime.now().year,
            },
        )
    return templates.TemplateResponse(
        request,
        "sponsorship.html",
        {
            "request": request,
            "state": "enter_recipient",
            "recipient_phone": phone or "",
            "current_year": datetime.now().year,
        },
    )


@web_router.post("/sponsorships")
async def create_sponsorship_checkout(
    request: Request,
    db: AsyncSession = Depends(get_db),
    recipient_phone: str = Form(...),
    plan_type: str = Form(...),
    gifter_phone: str = Form(...),
):
    """Create the Stripe checkout session for a generic (non-personalized)
    sponsorship — POST to the /sponsorships collection creates the
    checkout-session resource."""
    from app.services.stripe_service import create_gift_checkout_session

    clean_phone = format_to_e164(recipient_phone)
    if not clean_phone:
        return templates.TemplateResponse(
            request,
            "sponsorship.html",
            {
                "request": request,
                "state": "enter_recipient",
                "recipient_phone": recipient_phone,
                "error": "Invalid phone number. Use format: +1234567890",
                "current_year": datetime.now().year,
            },
        )

    clean_gifter_phone = format_to_e164(gifter_phone)
    if not clean_gifter_phone:
        return templates.TemplateResponse(
            request,
            "sponsorship.html",
            {
                "request": request,
                "state": "enter_recipient",
                "recipient_phone": recipient_phone,
                "error": "Invalid sponsor phone number. Use format: +1234567890",
                "current_year": datetime.now().year,
            },
        )

    base_url = str(request.base_url).rstrip("/")
    session = create_gift_checkout_session(
        recipient_phone=clean_phone,
        plan_type=plan_type,
        gifter_phone=clean_gifter_phone,
        success_url=f"{base_url}/sponsorships/new?status=success",
        cancel_url=f"{base_url}/sponsorships/new?status=canceled",
    )

    if not session.url:
        return templates.TemplateResponse(
            request,
            "sponsorship.html",
            {
                "request": request,
                "state": "enter_recipient",
                "recipient_phone": recipient_phone,
                "error": "Unable to create checkout session. Please try again.",
                "current_year": datetime.now().year,
            },
        )

    return RedirectResponse(url=session.url, status_code=status.HTTP_303_SEE_OTHER)


# Must be registered after /sponsorships/new to avoid shadowing it (and the
# app must include web_sponsorships_router — GET /sponsorships,
# POST /sponsorships/sign-in-links and the token-less GET
# /sponsorships/portal — before web_router, or this route would swallow
# those literal paths; see main.py).
@web_router.get("/sponsorships/{share_code}", response_class=HTMLResponse)
async def sponsorship_page(
    request: Request,
    share_code: str,
    db: AsyncSession = Depends(get_db),
    status_: str | None = Query(default=None, alias="status"),
    back: str | None = None,
):
    """Personalized sponsorship page keyed to the recipient's share code.

    Also renders the success/canceled states after Stripe redirects back
    here (?status=success|canceled). The success state looks the
    recipient's first name up server-side by share code — no name or
    phone rides in the Stripe-stored URL (PII — security.md).
    """
    if status_ == "success":
        recipient = await crud_user.get_by_share_code(db, share_code=share_code)
        return templates.TemplateResponse(
            request,
            "sponsorship.html",
            {
                "request": request,
                "state": "success",
                "recipient_name": _first_name(recipient, default="")
                if recipient
                else "",
                "current_year": datetime.now().year,
            },
        )
    if status_ == "canceled":
        return templates.TemplateResponse(
            request,
            "sponsorship.html",
            {
                "request": request,
                "state": "canceled",
                "back_url": safe_next_path(
                    back, default=f"/sponsorships/{share_code.upper()}"
                ),
                "current_year": datetime.now().year,
            },
        )

    recipient = await crud_user.get_by_share_code(db, share_code=share_code)
    if not recipient:
        return templates.TemplateResponse(
            request,
            "sponsorship.html",
            {"request": request, "state": "not_found"},
            status_code=404,
        )

    return templates.TemplateResponse(
        request,
        "sponsorship.html",
        {
            "request": request,
            "state": "known_recipient",
            "share_code": recipient.share_code,
            "recipient_first_name": _first_name(recipient, default="them"),
        },
    )


# POST /sponsorships/{code}/checkout is a sub-resource action (creates the
# Stripe checkout session for that recipient), not a bare noun route — an
# accepted REST deviation (backend-conventions.md).
@web_router.post("/sponsorships/{share_code}/checkout")
async def sponsorship_checkout(
    request: Request,
    share_code: str,
    db: AsyncSession = Depends(get_db),
    gifter_phone: str = Form(...),
    plan_type: str = Form(...),
):
    """Create Stripe checkout for a personalized sponsorship link."""
    from app.services.stripe_service import create_gift_checkout_session

    recipient = await crud_user.get_by_share_code(db, share_code=share_code)
    if not recipient or not recipient.phone:
        return RedirectResponse(
            url=f"/sponsorships/{share_code}", status_code=status.HTTP_303_SEE_OTHER
        )

    recipient_phone = recipient.phone.number
    base_url = str(request.base_url).rstrip("/")
    # No name or phone in the Stripe-stored URLs (PII); the success state
    # re-derives the first name from the share code server-side.
    recipient_path = f"/sponsorships/{recipient.share_code}"

    session = create_gift_checkout_session(
        recipient_phone=recipient_phone,
        plan_type=plan_type,
        gifter_phone=gifter_phone,
        success_url=f"{base_url}{recipient_path}?status=success",
        cancel_url=(
            f"{base_url}{recipient_path}?status=canceled&back={quote(recipient_path)}"
        ),
    )

    if not session.url:
        return RedirectResponse(
            url=f"/sponsorships/{share_code}", status_code=status.HTTP_303_SEE_OTHER
        )

    return RedirectResponse(url=session.url, status_code=status.HTTP_303_SEE_OTHER)


def _register_short_link_redirects() -> None:
    """Register one redirect per entry in the short-link registry
    (app/web/short_links.py): a coded entry gets ``/{slug}/{code}`` → 301
    ``{lander}/{CODE}``; the codeless ``/sub`` entry gets ``/sub`` → 302
    ``{lander}`` (no code to uppercase, and a temporary redirect — see the
    docstring below on why codeless stays 302).

    The per-slug policy (which lander, whether AASA-claimed) lives in the
    registry so the routes, the AASA path list (well_known.py), and the
    mobile app-link config stay in sync from one source. On an
    installed-app device the OS intercepts a claimed slug via universal
    links before the request reaches here; this redirect is the browser
    fallback for everyone else.
    """

    # Factory closure binds `lander` per slug WITHOUT exposing it as a
    # request parameter. (Binding it as a default arg on the handler
    # instead would make FastAPI treat it as a query param — an open
    # redirect: /r/x?_lander=//evil.com → 301 //evil.com/X.) `code` must
    # be the handler's only parameter so it's the sole path param.
    def _make_coded_redirect(lander: str):
        async def _redirect(code: str) -> RedirectResponse:
            return RedirectResponse(
                url=f"{lander}/{code.upper()}",
                status_code=status.HTTP_301_MOVED_PERMANENTLY,
            )

        return _redirect

    def _make_codeless_redirect(lander: str):
        async def _redirect() -> RedirectResponse:
            # 302, not 301: `/sub` rides in a frozen SMS body forever
            # (sub_lapse_notifications.py) — a 301 would let a browser
            # cache the redirect past any future change to where it points,
            # same reasoning the old interim marketing-bounce used.
            return RedirectResponse(url=lander, status_code=status.HTTP_302_FOUND)

        return _redirect

    for short_link in SHORT_LINKS:
        if short_link.has_code:
            web_router.add_api_route(
                f"/{short_link.slug}/{{code}}",
                _make_coded_redirect(short_link.lander),
                methods=["GET"],
                name=f"short_link_{short_link.slug}",
                include_in_schema=False,
            )
        else:
            web_router.add_api_route(
                f"/{short_link.slug}",
                _make_codeless_redirect(short_link.lander),
                methods=["GET"],
                name=f"short_link_{short_link.slug}",
                include_in_schema=False,
            )


_register_short_link_redirects()


def _register_nested_short_link_redirects() -> None:
    """Register one redirect per entry in NESTED_SHORT_LINKS
    (app/web/short_links.py): ``/{parent_slug}/{slug}/{value}`` -> 302
    ``{lander}/{value}``.

    302, not 301: the appended value is a one-time token that the lander
    consumes on first use (app/crud/sponsorship_sign_in_token.py) — a
    browser caching this redirect past that first use would be actively
    wrong, unlike the stable share/referral codes the coded top-level
    redirects carry. Case is PRESERVED (no ``.upper()``): the value is an
    opaque, case-sensitive token, not a human-typed code.
    """

    def _make_nested_redirect(lander: str):
        async def _redirect(value: str) -> RedirectResponse:
            return RedirectResponse(
                url=f"{lander}/{value}", status_code=status.HTTP_302_FOUND
            )

        return _redirect

    for nested in NESTED_SHORT_LINKS:
        web_router.add_api_route(
            f"/{nested.parent_slug}/{nested.slug}/{{value}}",
            _make_nested_redirect(nested.lander),
            methods=["GET"],
            name=f"short_link_{nested.parent_slug}_{nested.slug}",
            include_in_schema=False,
        )


_register_nested_short_link_redirects()


# The app-claimed Stripe checkout-return paths (app/web/short_links.py
# CLAIMED_APP_PATHS) — NOT short links. The request lands here whenever the
# OS doesn't hand the URL to the app: no app installed, desktop, or a Stripe
# return the OS declined to intercept (script-driven redirects often aren't
# — the app's confirming step and its foreground re-check are the reliable
# unlock path). Both go to the same store/marketing fallback: on a phone
# the store listing offers "Open" when the app is installed.
@web_router.get("/plans")
async def plans_web_fallback(request: Request) -> RedirectResponse:
    """Browser fallback for the app-claimed /plans path (the paywall, and
    where the registry-driven `/sub` redirect lands — see
    _register_short_link_redirects above — plus the Stripe success_url).
    An installed app MAY intercept this via universal link before it
    reaches the server."""
    target = store_redirect_url(
        request.headers.get("user-agent"), marketing_origin=settings.MARKETING_ORIGIN
    )
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


@web_router.get("/subscription")
async def subscription_web_fallback(request: Request) -> RedirectResponse:
    """Browser fallback for the app-claimed /subscription path (the
    Stripe customer-portal return_url). Same store/marketing fallback as
    /plans — see plans_web_fallback."""
    target = store_redirect_url(
        request.headers.get("user-agent"), marketing_origin=settings.MARKETING_ORIGIN
    )
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


@web_router.get("/groups/{invite_code}", response_class=HTMLResponse)
async def group_join_page(
    request: Request,
    invite_code: str,
    db: AsyncSession = Depends(get_db),
):
    """Minimal browser fallback for /g/{code} short URLs (301 here).

    Universal links route this URL into the installed app before the
    request hits the server. A user who lands here is on a device
    without the app (browser context, desktop, etc.), so the page just
    has to (a) confirm the code is real so we don't bounce bots to the
    App Store and (b) get them into the install flow with the code
    preserved for manual entry after install.
    """
    from app.crud.group_plan import crud_group_plan

    code_upper = invite_code.upper()
    plan = await crud_group_plan.get_by_invite_code(db, code=code_upper)
    if not plan:
        return templates.TemplateResponse(
            request,
            "group_join.html",
            {
                "request": request,
                "invalid_code": True,
                "current_year": datetime.now().year,
            },
        )
    owner_name = "A group member"
    if plan.owner and plan.owner.full_name:
        owner_name = plan.owner.full_name.split(" ")[0]
    return templates.TemplateResponse(
        request,
        "group_join.html",
        {
            "request": request,
            "invalid_code": False,
            "owner_name": owner_name,
            "invite_code": code_upper,
            "current_year": datetime.now().year,
        },
    )


async def _circle_invite_context(
    request: Request,
    db: AsyncSession,
    invite_code: str,
    current_user: User | None,
    *,
    just_accepted: bool = False,
) -> dict:
    """Template context for the circle-invite lander (GET /circles/{code}).
    The accept POST PRGs back to that GET (with ?accepted=1 on success);
    decline and leave PRG to GET /circles instead.

    Adds the viewer's membership state so the page can offer the right
    action: log in → accept on the web → done. Web acceptance makes a
    contact alertable WITHOUT installing the app (flow-review B1/3.2).
    """
    code_upper = invite_code.upper()
    inviter = await crud_user.get_by_circle_invite_code(
        db, circle_invite_code=code_upper
    )
    if not inviter:
        return {
            "request": request,
            "invalid_code": True,
            "current_year": datetime.now().year,
        }
    inviter_name = "A friend"
    if inviter.full_name:
        inviter_name = inviter.full_name.split(" ")[0]

    member_status: str | None = None
    is_self = False
    referral_code: str | None = None
    if current_user:
        if current_user.id == inviter.id:
            is_self = True
        else:
            member = await circle_invitations.get_member_for_accepter(
                db, inviter=inviter, accepter=current_user
            )
            # str() covers both the StrEnum member and raw-string states.
            member_status = str(member.status) if member else None
            # Referral offer on accept (owner decision): rendered only in
            # the just-accepted state (?accepted=1, set by the accept POST's
            # PRG redirect), not on a plain revisit. The marker is a bare
            # query param, so an ACTIVE member CAN replay it — cosmetic only:
            # POST /htmx/referrals/claim-from-invite enforces eligibility
            # server-side (valid referrer, not self, has_existing_referral,
            # plus the unique index on referrals.referee_user_id).
            if just_accepted and member_status == ContactStatus.ACTIVE.value:
                referral_code = await referral_service.referral_offer_for(
                    db, inviter=inviter, accepter=current_user
                )

    return {
        "request": request,
        "invalid_code": False,
        "inviter_name": inviter_name,
        "invite_code": code_upper,
        "logged_in": current_user is not None,
        "is_self": is_self,
        "member_status": member_status,
        "just_accepted": just_accepted,
        "referral_code": referral_code,
        "current_year": datetime.now().year,
    }


@web_router.get("/circles/{invite_code}", response_class=HTMLResponse)
async def circle_invite_page(
    request: Request,
    invite_code: str,
    accepted: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_from_cookie),
):
    """The Circle-invite lander — where /c/{invite_code} short URLs land
    (renamed from /circle/{invite_code}, owner decision 2026-09-23).

    /c/ is NOT app-claimed (Circle members use mobile web only, owner
    decision 2026-09-22/23 — see app/web/short_links.py), so every invitee
    lands here, app installed or not. Acceptance happens ON THE WEB (log
    in with phone OTP, tap accept) so a contact never has to install
    anything to become alertable; there is no app path to offer.

    ``?accepted=1`` is the PRG marker set by the accept POST's redirect —
    it's the only way this GET renders the "just accepted" copy and the
    referral offer instead of the plain "you're already a backup" state.
    """
    if gate := _require_name(current_user, request):
        return gate

    context = await _circle_invite_context(
        request, db, invite_code, current_user, just_accepted=accepted == "1"
    )
    return templates.TemplateResponse(request, "circle_invite.html", context)


@web_router.post("/circles/{invite_code}/accept", response_class=HTMLResponse)
async def circle_invite_accept(
    invite_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_from_cookie),
):
    """Accept a circle invite from the web lander (explicit consent step).

    Cookie-auth POST, same pattern as the other user-web actions. PRG:
    redirects back to the GET lander with ?accepted=1 so the accepted
    state (incl. DND-bypass guidance and the referral offer) renders from
    a fresh GET rather than leaving a re-submittable POST in history.
    """
    if not current_user:
        return RedirectResponse(
            url=f"/login?next=/circles/{quote(invite_code)}",
            status_code=status.HTTP_302_FOUND,
        )

    inviter = await crud_user.get_by_circle_invite_code(
        db, circle_invite_code=invite_code.upper()
    )
    accepted_now = False
    if inviter and inviter.id != current_user.id:
        try:
            await circle_invitations.accept_circle_invite(
                db, inviter=inviter, accepter=current_user
            )
            accepted_now = True
        except circle_invitations.NoPendingInviteError:
            # benign: already active (or no invite for this phone) — the
            # redirected GET renders that state on its own, no ?accepted=1.
            pass
        except circle_invitations.SelfAcceptError:
            # benign: unreachable given the id check above; kept for safety.
            pass
    suffix = "?accepted=1" if accepted_now else ""
    return RedirectResponse(
        url=f"/circles/{quote(invite_code)}{suffix}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@web_router.post("/circles/{invite_code}/decline", response_class=HTMLResponse)
async def circle_invite_decline(
    invite_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_from_cookie),
):
    """Decline a pending circle invite from the web (PRG back to /circles)."""
    if not current_user:
        return RedirectResponse(
            url=f"/login?next=/circles/{quote(invite_code)}",
            status_code=status.HTTP_302_FOUND,
        )

    inviter = await crud_user.get_by_circle_invite_code(
        db, circle_invite_code=invite_code.upper()
    )
    if inviter and inviter.id != current_user.id:
        await circle_invitations.decline_circle_invite(
            db, inviter=inviter, decliner=current_user
        )
    return RedirectResponse(url="/circles", status_code=status.HTTP_303_SEE_OTHER)


@web_router.post("/circles/{invite_code}/leave", response_class=HTMLResponse)
async def circle_invite_leave(
    invite_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_from_cookie),
):
    """Leave a circle from the web (PRG back to /circles). Soft-removes the
    ACTIVE membership row — a re-invite from the same inviter revives it."""
    if not current_user:
        return RedirectResponse(
            url=f"/login?next=/circles/{quote(invite_code)}",
            status_code=status.HTTP_302_FOUND,
        )

    inviter = await crud_user.get_by_circle_invite_code(
        db, circle_invite_code=invite_code.upper()
    )
    if inviter and inviter.id != current_user.id:
        await circle_invitations.leave_circle(db, inviter=inviter, member=current_user)
    return RedirectResponse(url="/circles", status_code=status.HTTP_303_SEE_OTHER)


# Display labels for an Alert row — the ONE place AlertType/AlertStatus map
# to user-facing copy, so no surface compares the lowercase enum values
# against uppercase strings in Jinja (alerts.html did exactly that, so no
# acknowledge button ever rendered and every alert read "Location Alert").
# Shared by the alerts list page (below) and the public alert page's header
# — keep it here, next to _alert_view_context, rather than duplicating.
def _alert_type_label(alert_type: AlertType) -> str:
    if alert_type == AlertType.PANIC:
        return "SOS alert"
    if alert_type == AlertType.MISSED_SESSION:
        return "Missed check-in alert"
    # AlertType.REMINDER is a legacy/unused enum value: nothing creates an
    # Alert row with it — the circle re-nudge (notification_outbox.
    # _enqueue_renudge) is an outbox delivery, not an Alert row, so one
    # incident never lists twice. The label is only a defensive fallback.
    return "Reminder"


def _is_no_longer_current(session: SessionModel, *, now: datetime) -> bool:
    """The never-resolved-incident predicate (.claude/rules/
    domain-sessions-alerts.md, "Never-resolved incidents", owner decisions
    2026-07-19): an admin-CANCELLED session (closed false alarm), or one
    stuck MISSED/ALERTED past ALERT_PAGE_MAX_AGE_DAYS from its deadline.
    Such an incident renders the neutral "no longer current" card on the
    public page and the "No longer current" label on the alerts list; the
    same cutoff (crud.alert.stale_incident_cutoff) keeps it out of the nav
    badge. COMPLETED is never "no longer current" — the all-clear wins."""
    if str(session.status) == SessionStatus.CANCELLED.value:
        return True
    return str(session.status) in (
        SessionStatus.MISSED.value,
        SessionStatus.ALERTED.value,
    ) and session.expected_return_time < stale_incident_cutoff(now)


def _alert_status_label(
    alert: Alert, session: SessionModel | None, *, now: datetime
) -> str:
    # The session's outcome wins first: a COMPLETED session is an all-clear
    # and a CANCELLED/aged-out one is no longer current, whatever the alert's
    # own status says. RESOLVED (set only by mark-safe or admin close, which
    # also end the session) reads as the all-clear it means.
    if session is not None:
        if str(session.status) == SessionStatus.COMPLETED.value:
            return "All clear"
        if _is_no_longer_current(session, now=now):
            return "No longer current"
    if alert.status == AlertStatus.RESOLVED:
        return "All clear"
    if alert.status == AlertStatus.ACKNOWLEDGED:
        return "Acknowledged"
    if alert.status == AlertStatus.FAILED:
        return "Delivery failed"
    return "New"  # SENT or DELIVERED


_STATUS_BADGE_CLASS = {
    "New": "badge-emergency",
    "Acknowledged": "badge-active",
    "All clear": "badge-active",
    "No longer current": "badge-pending",
    "Delivery failed": "badge-emergency",
}


def _alert_list_row(alert: Alert, *, now: datetime) -> dict:
    """One alert as a list row — who/what/when/status only. Nothing the
    circle-viewer snapshot gates (location, phone, photo) goes in here; the
    row links to GET /alerts/{id} for details. Expects alert.session.user
    eager-loaded (crud_alert.get_user_alerts)."""
    session = alert.session
    owner_first = "Your friend"
    sent_at_local = None
    if session is not None:
        sent_at_local = _format_local_datetime(alert.sent_at, session.tz_offset_minutes)
        if session.user and session.user.full_name:
            owner_first = session.user.full_name.split(" ")[0]
    status_label = _alert_status_label(alert, session, now=now)
    return {
        "id": alert.id,
        "owner_first": owner_first,
        "type_label": _alert_type_label(alert.alert_type),
        "status_label": status_label,
        "status_badge_class": _STATUS_BADGE_CLASS[status_label],
        "sent_at_local": sent_at_local,
    }


async def _alert_view_context(
    request: Request, db: AsyncSession, alert_id: str
) -> dict:
    """Context for the public alert page. The UUID is the access token —
    unguessable (uuid4), shared only with the alerted contact via SMS."""
    from uuid import UUID as _UUID

    from sqlalchemy.orm import selectinload

    from app.crud.session import crud_session
    from app.models.alert import Alert, AlertType
    from app.models.session import Session as SessionModel
    from app.models.session import SessionStatus
    from app.services import photo_urls
    from app.services.circle_view import build_session_snapshot
    from app.services.session_tasks import _format_local_time
    from app.utils.phone import format_for_display

    base: dict = {"request": request, "current_year": datetime.now().year}
    try:
        aid = _UUID(alert_id)
    except ValueError:
        # benign: a malformed alert id renders the not-found card
        return {**base, "not_found": True}

    result = await db.execute(select(Alert).where(Alert.id == aid))
    alert = result.scalar_one_or_none()
    if not alert or not alert.session_id:
        return {**base, "not_found": True}

    sess_result = await db.execute(
        select(SessionModel)
        .options(
            selectinload(SessionModel.user),
        )
        .where(SessionModel.id == alert.session_id)
    )
    session = sess_result.scalar_one_or_none()
    if not session:
        return {**base, "not_found": True}

    # Shared circle-viewer snapshot — the same fields the mobile alert payload
    # serves (services/circle_view.py), so the two surfaces can't drift.
    snapshot = build_session_snapshot(session)
    owner_first = (snapshot["user_name"] or "Your friend").split(" ")[0]
    battery = snapshot["last_battery_level"]
    last_ping = snapshot["last_location_update"]

    # Never-resolved staleness (owner decision 2026-07-19): a session stuck
    # MISSED/ALERTED past ALERT_PAGE_MAX_AGE_DAYS — or admin-CANCELLED (a
    # closed false alarm) — stops serving the live incident view: no
    # location, phone or Acknowledge, just a neutral card pointing
    # at law enforcement. COMPLETED still always wins (all-clear card).
    no_longer_current = _is_no_longer_current(session, now=datetime.now(UTC))

    # Acknowledge shows for EVERY recipient, including a sole contact (owner
    # decision 2026-07-19, reversing the old >1 coordination gate): the
    # acknowledgement's primary job is the OWNER's confirmation that a human
    # saw the alert — exactly as valuable with one contact as with five, and
    # 1-contact circles are the common case.

    # Location trail for the MapLibre map — only on the LIVE view (the
    # all-clear / no-longer-current cards show no location) and only when
    # the owner shared location. Passed as a plain list and serialised by
    # the template's |tojson (HTML-safe: escapes <, >, &, ') — never built
    # by hand in Jinja (rules/security.md: user data reaching JS is
    # JSON-serialised). Coordinates only — the map script needs nothing else.
    all_clear = str(session.status) == SessionStatus.COMPLETED.value
    trail: list[dict] = []
    if snapshot["location_sharing_enabled"] and not all_clear and not no_longer_current:
        updates = await crud_session.get_location_history(db, session_id=session.id)
        trail = [
            {"lat": u.latitude, "lng": u.longitude}
            for u in updates
            if u.latitude is not None and u.longitude is not None
        ]

    battery_state = snapshot["last_battery_state"]

    return {
        **base,
        "not_found": False,
        "alert": alert,
        "alert_id": str(alert.id),
        "is_sos": alert.alert_type == AlertType.PANIC,
        "alert_type_label": _alert_type_label(alert.alert_type),
        "owner_first": owner_first,
        # "From" shows the full name, as the native screen did — the SMS the
        # recipient got already carries it. Everywhere else uses owner_first.
        "owner_full_name": snapshot["user_name"] or owner_first,
        "owner_phone_e164": snapshot["user_phone"],
        "owner_phone_display": format_for_display(snapshot["user_phone"] or ""),
        "all_clear": all_clear,
        "no_longer_current": no_longer_current,
        "destination": snapshot["destination"],
        "expected_return_local": _format_local_time(
            snapshot["return_time"], snapshot["tz_offset_minutes"]
        )
        if snapshot["return_time"] is not None
        else None,
        # The location toggle gates what the owner chose to share, so the page
        # never shows data the owner turned off. Battery has no toggle — it's
        # always shared. The snapshot already nulls location when the toggle
        # is off.
        "location_sharing_enabled": snapshot["location_sharing_enabled"],
        "latitude": snapshot["last_known_latitude"],
        "longitude": snapshot["last_known_longitude"],
        "battery_pct": round(battery * 100) if battery is not None else None,
        "last_ping_local": _format_local_time(last_ping, snapshot["tz_offset_minutes"])
        if last_ping is not None
        else None,
        "acknowledged": alert.acknowledged_at is not None,
        "sent_at": alert.sent_at,
        "message": alert.message,
        "sent_at_local": _format_local_datetime(
            alert.sent_at, snapshot["tz_offset_minutes"]
        ),
        # "Charging" is the only battery_state rendered — the other values
        # ("unplugged"/"full"/"unknown", see mobile/types/index.ts) aren't
        # worth a safety-page line.
        "battery_state": battery_state,
        "outfit_photo_url": photo_urls.to_viewable_url(snapshot["outfit_photo_url"]),
        "trail": trail,
    }


@web_router.get("/alerts/{alert_id}", response_class=HTMLResponse)
async def alert_view_page(
    request: Request,
    alert_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Public alert details for the contact who received the alert SMS.

    No auth: the recipient may have no app and no account — this page is
    how an SMS-only contact sees location/details and claims the alert
    (docs/flow-review.md §4.3/3.3). The alert UUID is the access token.
    """
    context = await _alert_view_context(request, db, alert_id)
    return templates.TemplateResponse(request, "alert_view.html", context)


@web_router.post("/alerts/{alert_id}/acknowledge", response_class=HTMLResponse)
async def alert_acknowledge(
    request: Request,
    alert_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge from the public alert page, then PRG-redirect to the GET.

    The browser must never sit parked on a re-submittable POST — the form
    submit itself is script-free, so a redirect is the only script-free way
    off it even though the page also loads the trail-map JS: reload/back
    after acknowledging are then plain GETs, and the redirected page
    renders the real state (checked button, or the all-clear card if the
    owner marked safe meanwhile). The all_clear/acknowledged gates keep a
    late submit from re-acknowledging (acknowledge_alert has the same
    terminal guard server-side)."""
    from app.services import alert_acknowledgement

    context = await _alert_view_context(request, db, alert_id)
    if (
        not context.get("not_found")
        and not context.get("acknowledged")
        and not context.get("all_clear")
        and not context.get("no_longer_current")
    ):
        await alert_acknowledgement.acknowledge_alert(db, alert=context["alert"])
    return RedirectResponse(
        url=f"/alerts/{quote(alert_id)}", status_code=status.HTTP_303_SEE_OTHER
    )


@web_router.get("/made-it-home.vcf")
async def made_it_home_vcard():
    """Downloadable contact card for the Made It Home alert number.

    Step one of the DND-bypass guidance (flow-review §4.4b): save the
    contact, then enable iOS Emergency Bypass / Android starred-contact so
    alert texts ring through Do Not Disturb.
    """
    number = settings.SMS_DISPLAY_NUMBER or settings.TWILIO_PHONE_NUMBER
    vcard = (
        "BEGIN:VCARD\r\n"
        "VERSION:3.0\r\n"
        # Stable UID so clients that honor it update this contact in place on
        # re-download instead of creating a duplicate (best-effort — iOS often
        # still duplicates on a manually-opened .vcf; Android/Google merges).
        "UID:made-it-home-alerts\r\n"
        # N (structured name) is required by vCard 3.0 and is what iOS uses to
        # populate the First/Last fields — without it iOS shows a blank name.
        # Order is Family;Given;Additional;Prefix;Suffix. Portable: iOS and
        # Android both read N, no Apple-only extension needed.
        "N:Alerts;Made It Home;;;\r\n"
        "FN:Made It Home Alerts\r\n"
        "ORG:Made It Home\r\n"
        f"TEL;TYPE=CELL:{number}\r\n"
        "NOTE:Alerts for people who added you to their Circle of "
        "Trust. Enable Emergency Bypass (iPhone) or star this contact "
        "(Android) so alerts ring through Do Not Disturb.\r\n"
        "END:VCARD\r\n"
    )
    return Response(
        content=vcard,
        media_type="text/vcard",
        headers={"Content-Disposition": 'attachment; filename="made-it-home.vcf"'},
    )


@web_router.get("/referrals/{code}", response_class=HTMLResponse)
async def referral_page(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Referral landing page - shows referrer info + auth flow"""
    referrer = await crud_user.get_by_share_code(db, share_code=code)

    if not referrer:
        return templates.TemplateResponse(
            request,
            "referral.html",
            {
                "request": request,
                "invalid_code": True,
                "current_year": datetime.now().year,
            },
        )

    first_name = (referrer.full_name or "A friend").split(" ")[0]
    return templates.TemplateResponse(
        request,
        "referral.html",
        {
            "request": request,
            "referrer_name": first_name,
            "referral_code": code.upper(),
            "invalid_code": False,
            "current_year": datetime.now().year,
        },
    )


# /terms and /privacy used to render templates here. The canonical legal
# pages now live at the marketing site (https://www.madeithomeapp.com/),
# so the routes are removed entirely and the footer links point absolute.


@web_router.get("/logout")
async def logout():
    """Logout and redirect to the login page.

    Marketing lives only on the marketing-site repo (owner decision
    2026-09-23), so there is no in-app `/` to land on after logout.
    """

    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_auth_cookie(response)
    return response
