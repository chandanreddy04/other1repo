import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.api import api_router
from app.api.v1.endpoints import delivery_webhooks, inbound_sms, webhooks, well_known
from app.core.config import settings
from app.core.error_reporting import is_accounted_for
from app.core.error_reporting import is_configured as error_reporting_configured
from app.core.error_reporting import notify as report_error
from app.core.errors import UpstreamUnavailable
from app.core.logging import setup_logging
from app.core.rate_limit import limiter
from app.core.startup_checks import run_production_startup_checks
from app.core.version import git_sha
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.web.routes_admin import admin_router
from app.web.routes_htmx_auth import router as htmx_auth_router
from app.web.routes_htmx_referral import router as htmx_referral_router
from app.web.routes_htmx_sponsorships import router as htmx_sponsorships_router
from app.web.routes_web import web_router
from app.web.routes_web_delete import router as web_delete_router
from app.web.routes_web_sponsorships import router as web_sponsorships_router

setup_logging()  # also configures Bugsnag (release_stage from ENVIRONMENT)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Made It Home API")
    run_production_startup_checks(settings)
    yield
    logger.info("Shutting down Made It Home API")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(RequestIDMiddleware)


@app.exception_handler(StarletteHTTPException)
async def _report_5xx_http_exceptions(request: Request, exc: StarletteHTTPException):
    """Deliberate 5xx responses (`raise HTTPException(502) from e` around Stripe,
    S3, ...) are converted by Starlette before ErrorHandlerMiddleware sees them,
    so they'd never reach Bugsnag. Report them here — with the original cause
    when the raise site used `from e` — then render FastAPI's normal response."""
    if exc.status_code >= 500:
        # Severity is explicit, never inferred from the status: UpstreamUnavailable
        # (a provider blip the endpoint is designed to translate) is a WARNING;
        # every other 5xx — a bare 500, a fail-closed 503 for a misconfigured
        # secret — is a defect (ERROR).
        defect = not isinstance(exc, UpstreamUnavailable)
        logger.log(
            logging.ERROR if defect else logging.WARNING,
            "HTTP %s on %s %s: %s",
            exc.status_code,
            request.method,
            request.url.path,
            exc.detail,
            extra={"error_report_skip": True},
        )
        # `logger.error(...)` then `raise HTTPException(503)` in the same except
        # block: the forwarder stamped the exception being handled, which is
        # this one's __context__ — one report, not two. A 5xx raised outside
        # any except block has no __context__ and is always its own report.
        already_reported = (
            exc.__cause__ is None
            and not exc.__suppress_context__
            and is_accounted_for(exc.__context__)
        )
        if not already_reported:
            report_error(
                exc.__cause__ or exc,
                context=f"{request.method} {request.url.path}",
                metadata={
                    "http": {"status_code": exc.status_code, "detail": str(exc.detail)}
                },
                severity="error" if defect else "warning",
            )
    return await http_exception_handler(request, exc)


app.include_router(api_router, prefix=settings.API_V1_STR)

# Inbound webhooks live at the top level, outside the versioned client API:
# they are server-to-server event sinks (Stripe payments, Twilio/SNS SMS
# delivery), not endpoints the mobile/web clients call. App-level middleware
# (request ID, error handling, rate limiting) still applies.
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(
    delivery_webhooks.router, prefix="/webhooks", tags=["delivery-webhooks"]
)
app.include_router(inbound_sms.router, prefix="/webhooks", tags=["inbound-sms"])

# Universal-link / app-link manifests at /.well-known/. These are claimed
# by the iOS / Android OS at app install time so /r/, /g/, /sub, /plans and
# /subscription URLs open the app directly when present (sponsorship
# checkout /s/, Circle invites /c/, and /sponsorships are deliberately NOT
# claimed — see well_known.py / short_links.py for the IAP / Circle-web-only
# rationale). Top-level routing — NOT under /api/v1.
app.include_router(well_known.router, prefix="/.well-known", tags=["well-known"])

# Public phone-keyed sponsorship-management flow — magic link → Stripe
# billing portal. See docs/account-deletion-plan.md Phase 7.5. Included
# BEFORE web_router: its literal GET /sponsorships and POST /sponsorships/
# sign-in-links routes must be matched before web_router's
# GET /sponsorships/{share_code} (personalized checkout page) would
# otherwise swallow them as a share_code path param. GET /sponsorships/
# portal/{token} has an extra path segment, so it can't collide with
# {share_code} regardless of include order.
app.include_router(web_sponsorships_router)
# Include web routes for Circle of Trust members
app.include_router(web_router)
# Public cold-start account-deletion flow (Google Play / Apple require
# a web-accessible deletion path; see docs/account-deletion-plan.md).
app.include_router(web_delete_router)
app.include_router(htmx_auth_router)
app.include_router(htmx_sponsorships_router)
app.include_router(htmx_referral_router)
app.include_router(admin_router)

# Serve static files (favicon, etc.)
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

# Serve uploaded files locally in development
if settings.ENVIRONMENT == "development":
    from app.services.file_upload import LOCAL_UPLOAD_DIR

    LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(LOCAL_UPLOAD_DIR)), name="uploads")


@app.get("/health")
async def health_check():
    """Lightweight liveness probe — confirms the process is running."""
    return {
        "status": "healthy",
        "service": "Made It Home API",
        "version": git_sha(),
    }


@app.get("/health/ready")
async def readiness_check():
    """Deep readiness probe — verifies database connectivity. Also reports
    whether error reporting is configured (informational — never flips readiness)."""
    checks: dict[str, str] = {}

    try:
        from sqlalchemy import text

        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        # benign: a readiness-probe result — a DB outage alarms via RDS/ALB
        # metrics, not via one event per probe.
        # Log the detail server-side; the public readiness body must not leak
        # the DSN/host/internal error text (this endpoint is reachable via the
        # ALB and is the Cloudflare failover probe target).
        logging.getLogger("app.main").warning("readiness DB check failed: %s", e)
        checks["database"] = "error"

    checks["error_reporting"] = (
        "configured" if error_reporting_configured() else "unconfigured"
    )

    all_ok = checks["database"] == "ok"
    status_code = 200 if all_ok else 503

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ok else "degraded",
            "checks": checks,
        },
    )
