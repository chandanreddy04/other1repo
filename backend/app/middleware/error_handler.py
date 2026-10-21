"""Last-resort request error handling — the 500 response + the Bugsnag report.

Unhandled exceptions are reported to Bugsnag as *unhandled* (they count against
stability) with the request context; the log line is marked ``error_report_skip`` so
the root-logger forwarder doesn't report the same exception twice. The request
context (method, path, authenticated user.id) is published for the whole
request via ``request_context_var`` so log-forwarded events from deeper in the
stack carry it too.

Deliberate ``HTTPException`` responses never reach this middleware (Starlette
converts them first) — 5xx ones are reported by the handler in app/main.py.

Related: app/core/error_reporting.py, app/core/logging.py, app/main.py,
tests/test_error_handler.py, tests/test_error_reporting_plumbing.py.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.core.error_reporting import notify as report_error
from app.core.logging import request_context_var

logger = logging.getLogger(__name__)


def _extract_user_id(request: Request) -> str | None:
    """Best-effort user_id from the Bearer token (API) or the auth cookie
    (web/admin). Returns None on any failure."""
    auth = request.headers.get("authorization", "")
    token = (
        auth[7:] if auth.startswith("Bearer ") else request.cookies.get("access_token")
    )
    if not token:
        return None
    try:
        from app.core.security import decode_access_token

        token_data = decode_access_token(token)
        return token_data.sub if token_data else None
    except Exception:
        # benign: attribution is best-effort; an undecodable token just means no user.id
        logger.debug(
            "could not decode bearer token for error attribution", exc_info=True
        )
        return None


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Global error handler that logs unhandled exceptions and reports to Bugsnag."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        token = request_context_var.set(
            {
                "method": request.method,
                "path": request.url.path,
                "user_id": _extract_user_id(request),
            }
        )
        try:
            return await call_next(request)
        except Exception as exc:
            logger.exception(
                "Unhandled exception on %s %s",
                request.method,
                request.url.path,
                extra={"error_report_skip": True},
            )
            # Query string deliberately not reported — some endpoints take a
            # phone number as a query param (PII; only user.id may go).
            report_error(
                exc,
                context=f"{request.method} {request.url.path}",
                unhandled=True,
            )
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
            )
        finally:
            request_context_var.reset(token)
