"""Error reporting (Bugsnag today) — the one place the tracker is wired up.

Two delivery paths, both configured here:

1. The root-logger ``BugsnagHandler`` (ERROR and above). Every
   ``logger.error`` / ``logger.exception`` / ``logger.critical`` in the codebase
   becomes a Bugsnag event. This is what the swallow-and-log pattern relies on
   (``worker_tick._safe``, the service-layer ``except`` blocks, the outbox):
   before 2026-09-06 the handler was never attached, so those logs reached
   stdout and nothing else — which is why Bugsnag stayed empty.
2. Explicit ``notify()`` for the few sites that know more than a log record
   does: unhandled request exceptions (``middleware/error_handler.py``,
   reported as *unhandled*), deliberate ``HTTPException`` 5xx responses
   (``main.py``), and the smoke test. Those sites log with
   ``extra={"error_report_skip": True}`` so the handler doesn't report them twice.

Every event gets the current request's method/path/request_id and the
authenticated ``user.id`` from ``request_context_var`` via ``before_notify``,
and every E.164 phone number in its error message, context or metadata is
redacted there — provider exceptions (Twilio, SNS) embed the destination
number in their text, and nothing else would strip it.

Duplicates: an exception the log forwarder already sent (``logger.exception``
then ``raise``) is skipped by ``notify()`` — it matches on exception identity.
The ``HTTPException(5xx) from e`` handler also matches ``__cause__``; the
unhandled path (middleware) deliberately does NOT, because Starlette re-raises
with a synthetic ``from __context__`` and a genuinely new failure raised after
logging would otherwise be dropped.

Gating: no API key → nothing is configured (``error_reporting_unconfigured`` is logged
at ERROR in staging/production and ``startup_checks`` refuses to boot there).
``release_stage`` is ``ENVIRONMENT`` and only ``NOTIFY_RELEASE_STAGES`` are
delivered, so dev/test never send.

PII: only ``user.id`` may reach Bugsnag (security.md). Never log a phone number
at ERROR or above — ``tests/test_log_phone_pii_guard.py``,
``tests/test_no_phone_in_log_extras.py`` and
``tests/test_log_phone_positional_guard.py`` enforce it; ``PARAMS_FILTERS``
redacts phone-like metadata keys as a last line of defence.

Related: app/core/logging.py (``setup_logging`` calls ``configure``),
app/core/startup_checks.py, app/middleware/error_handler.py, app/main.py,
app/web/routes_admin.py (admin smoke button), scripts/error_reporting_smoke.py,
tests/test_error_reporting_plumbing.py.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sys
from typing import Any

from bugsnag.handlers import BugsnagHandler

from app.core.config import Settings, settings
from app.core.logging import (
    request_context_var,
    request_id_var,
)
from app.core.version import git_sha

NOTIFY_RELEASE_STAGES: tuple[str, ...] = ("production", "staging")
HANDLER_NAME = "error_reporting"
# Metadata KEYS Bugsnag redacts (case-insensitive SUBSTRING match, so only
# unambiguous phone-shaped names — "to"/"from"/"number" would eat "timeout_s",
# "attempt_number", ...). The real defence is the value redaction below.
PARAMS_FILTERS = [
    "password",
    "password_confirmation",
    "cookie",
    "authorization",
    "phone",
    "phone_number",
    "recipient",
    "sender",
    "e164",
]
# E.164 numbers anywhere in event text → "[PHONE]". Twilio/SNS exception
# messages ("The 'To' number +1415… is not valid") are the known carriers.
_PHONE_RE = re.compile(r"\+[1-9]\d{6,14}")
PHONE_REDACTED = "[PHONE]"
# Every `extra={...}` key on a log record rides along in the event's "extra"
# tab (phone-redacted, non-JSON values stringified). An allow-list rotted the
# first time a site logged a key it didn't know about.
_STD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", logging.ERROR, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}
_PRIVATE_EXTRAS = frozenset({"error_report_skip"})

logger = logging.getLogger(__name__)
_configured = False
_callback_registered = False
# Marker set on an exception the log forwarder already reported, so an
# explicit notify() of the same exception — or of one raised `from` it — is a
# no-op instead of a duplicate event. (An attribute, not a WeakSet: built-in
# exception instances can't be weak-referenced.)
_FORWARDED_ATTR = "_error_reporting_forwarded"
# Marker set on the exception being HANDLED when a message-only ERROR record
# (no exc_info) is logged inside its except block. Weaker than the one above:
# it only tells the 5xx handler that a cause-less `raise HTTPException(5xx)`
# which follows is the same failure — never enough to suppress an unhandled
# report, because no traceback was ever sent.
_LOGGED_ATTR = "_error_reporting_logged"


class ErrorReportingSmokeTestError(Exception):
    """A deliberate test event (admin dashboard button, scripts/error_reporting_smoke.py)."""


class _LogForwarder(BugsnagHandler):
    """Root-logger handler. Records logged with ``extra={"error_report_skip": True}``
    were already reported by an explicit ``notify()`` with richer context."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.add_callback(self._annotate)

    @staticmethod
    def _annotate(record: logging.LogRecord, options: dict[str, Any]) -> None:
        # A message-only record has no stack of its own — every one would land
        # in a single "LogERROR" group. Group by logger + UNFORMATTED template
        # instead (an f-string defeats this — tests/test_log_error_message_
        # templates.py), so "Twilio failover" and "stuck MISSED sessions" are
        # distinct alarms.
        if not record.exc_info:
            options.setdefault("grouping_hash", f"{record.name}:{record.msg}")
        phase = getattr(record, "phase", None)
        if phase:
            options["context"] = phase
        custom = {
            key: _scrub(value)
            for key, value in record.__dict__.items()
            if key not in _STD_RECORD_ATTRS and key not in _PRIVATE_EXTRAS
        }
        if custom:
            options.setdefault("metadata", {}).setdefault("extra", {}).update(custom)

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "error_report_skip", False):
            return False
        # Since 3.12 a filter may return a replacement LogRecord; keep the bool.
        return bool(super().filter(record))

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info:
            _stamp(record.exc_info[1], _FORWARDED_ATTR)  # reported, with traceback
        else:
            _stamp(sys.exc_info()[1], _LOGGED_ATTR)  # accounted for, no traceback
        super().emit(record)


def _stamp(exc: BaseException | None, attr: str) -> None:
    if isinstance(exc, BaseException):
        # benign: an exception type without __dict__ simply can't dedupe
        with contextlib.suppress(AttributeError):
            setattr(exc, attr, True)


def _scrub(value: Any) -> Any:
    """Phone-redacted, JSON-shaped copy (UUIDs, datetimes, ... become strings)."""
    if isinstance(value, str):
        return _PHONE_RE.sub(PHONE_REDACTED, value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(k): _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_scrub(v) for v in value]
    return _PHONE_RE.sub(PHONE_REDACTED, str(value))


def _redact_phone_numbers(event: Any) -> None:
    for error in getattr(event, "errors", None) or []:
        error.error_message = _scrub(error.error_message)
    if event.context:
        event.context = _scrub(event.context)
    if event.grouping_hash:
        event.grouping_hash = _scrub(event.grouping_hash)
    event.metadata = _scrub(event.metadata)
    for crumb in event.breadcrumbs:
        _scrub_breadcrumb(crumb)


def _scrub_breadcrumb(breadcrumb: Any) -> None:
    """``on_breadcrumb`` callback (and belt-and-braces at notify time): the SDK
    leaves an ERROR breadcrumb for every event it delivers, and
    breadcrumbs are shared process-wide, so a Twilio message with a phone number
    would otherwise ride along on the next event."""
    breadcrumb.message = _scrub(breadcrumb.message)
    breadcrumb.metadata = _scrub(breadcrumb.metadata)


def _attach_request_context(event: Any) -> None:
    ctx = request_context_var.get()
    request_tab: dict[str, Any] = {"request_id": request_id_var.get(None)}
    if ctx:
        request_tab["method"] = ctx.get("method")
        request_tab["path"] = ctx.get("path")
        user_id = ctx.get("user_id")
        if user_id and not event.user.get("id"):
            event.set_user(id=user_id)
    event.add_tab("request", request_tab)


def _enrich_event(event: Any) -> None:
    """``before_notify`` callback for EVERY event (explicit or log-forwarded):
    user.id + request tab, then phone-number redaction over all event text."""
    _attach_request_context(event)
    _redact_phone_numbers(event)


def _detach_handler() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == HANDLER_NAME:
            root.removeHandler(handler)


def configure(cfg: Settings = settings) -> bool:
    """Configure the client and attach the log forwarder. Returns whether
    Bugsnag is live. Idempotent — safe to call from every entrypoint."""
    global _configured, _callback_registered
    _detach_handler()
    if not cfg.BUGSNAG_API_KEY:
        _configured = False
        level = (
            logging.ERROR if cfg.ENVIRONMENT in NOTIFY_RELEASE_STAGES else logging.DEBUG
        )
        logger.log(
            level,
            "error_reporting_unconfigured: BUGSNAG_API_KEY is blank for ENVIRONMENT=%s — "
            "nothing will be reported",
            cfg.ENVIRONMENT,
        )
        return False

    import bugsnag
    import bugsnag.legacy

    bugsnag.configure(
        api_key=cfg.BUGSNAG_API_KEY,
        project_root="/app",
        release_stage=cfg.ENVIRONMENT,
        notify_release_stages=list(NOTIFY_RELEASE_STAGES),
        app_version=git_sha(),
        params_filters=PARAMS_FILTERS,
    )
    if not _callback_registered:
        bugsnag.before_notify(_enrich_event)
        bugsnag.legacy.default_client.add_on_breadcrumb(_scrub_breadcrumb)
        _callback_registered = True

    handler = _LogForwarder()
    handler.set_name(HANDLER_NAME)
    handler.setLevel(logging.ERROR)
    logging.getLogger().addHandler(handler)
    _configured = True
    logger.info(
        "error_reporting_configured release_stage=%s app_version=%s",
        cfg.ENVIRONMENT,
        git_sha(),
    )
    return True


def is_configured() -> bool:
    return _configured


def notify(
    exc: BaseException,
    *,
    context: str,
    metadata: dict[str, dict[str, Any]] | None = None,
    severity: str = "error",
    unhandled: bool = False,
    severity_reason: dict[str, Any] | None = None,
) -> bool:
    """Explicit report. Prefer ``logger.error``/``logger.exception`` everywhere
    else — the root handler forwards those. Returns whether a report was sent
    (False when unconfigured, or when the forwarder already sent this exception)."""
    if not _configured:
        return False
    if _already_forwarded(exc, include_cause=not unhandled):
        return False

    import bugsnag.legacy

    if severity_reason is None:
        if unhandled:
            severity_reason = {
                "type": "unhandledExceptionMiddleware",
                "attributes": {"framework": "FastAPI"},
            }
        elif severity != "error":
            severity_reason = {"type": "userSpecifiedSeverity"}
        else:
            severity_reason = {"type": "handledException"}
    options: dict[str, Any] = {
        "context": context,
        "severity": severity,
        "severity_reason": severity_reason,
        "metadata": metadata or {},
    }
    if unhandled:
        options["unhandled"] = True
    # The client directly, not bugsnag.notify(): the legacy wrapper overwrites
    # severity_reason with "userSpecifiedSeverity" whenever severity is given.
    bugsnag.legacy.default_client.notify(exc, **options)
    return True


def was_forwarded(exc: BaseException | None) -> bool:
    """Whether the log forwarder already reported this exception (with its
    traceback) — the only thing that makes a later report of it a duplicate."""
    return exc is not None and bool(getattr(exc, _FORWARDED_ATTR, False))


def is_accounted_for(exc: BaseException | None) -> bool:
    """Reported, or at least logged at ERROR (message-only) while being handled.
    For main.py's 5xx handler: a cause-less `raise HTTPException(5xx)` in that
    same except block is this failure's response, not a second failure."""
    return exc is not None and (
        was_forwarded(exc) or bool(getattr(exc, _LOGGED_ATTR, False))
    )


def _already_forwarded(exc: BaseException, *, include_cause: bool) -> bool:
    """The exception itself was forwarded — or, for handled reports, the one it
    was raised ``from``. Never ``__context__`` here: a fresh exception raised
    inside an except block that just logged is a new failure (the 5xx handler
    in main.py makes the one designed exception to that). Unhandled reports
    skip ``__cause__`` too, because Starlette's BaseHTTPMiddleware re-raises
    every exception as ``raise exc from exc.__cause__ or exc.__context__``."""
    candidates = [exc, exc.__cause__] if include_cause else [exc]
    return any(was_forwarded(candidate) for candidate in candidates)


def reset_for_tests() -> None:
    """Detach the log forwarder and forget the configured state."""
    global _configured
    _detach_handler()
    _configured = False
