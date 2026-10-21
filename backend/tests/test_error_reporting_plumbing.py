"""Bugsnag actually receives what the app believes it reports.

Before 2026-09-06 the codebase assumed ``logger.error``/``logger.exception``
forwarded to Bugsnag, but no handler was ever attached: the worker's ``_safe``
wrapper and every service-layer ``except`` block reported nothing, deliberate
5xx responses bypassed the reporting middleware, and a blank key was a silent
no-op. These tests pin every delivery path end to end through the real app and
worker code, with the SDK's own client entry points captured so nothing leaves
the process.

Related: app/core/error_reporting.py, app/middleware/error_handler.py, app/main.py,
app/core/startup_checks.py, worker_tick.py, app/web/routes_admin.py.
"""

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bugsnag.legacy
import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.core import error_reporting as reporting
from app.core.config import settings
from app.core.errors import UpstreamUnavailable
from app.core.logging import request_context_var
from app.core.security import create_access_token
from app.core.startup_checks import (
    _check_error_reporting,
    run_production_startup_checks,
)
from app.main import app
from app.web.csrf import CSRF_COOKIE_NAME, CSRF_FORM_FIELD, generate_csrf_token
from tests.helpers import create_test_user

FAKE_KEY = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):
    """Bugsnag configured with a fake key. The SDK's ``configure`` is patched (no
    real client state) and the default client's ``notify`` / ``notify_exc_info``
    — the two entry points the log forwarder and ``notify()`` use — are captured."""
    monkeypatch.setattr(settings, "BUGSNAG_API_KEY", FAKE_KEY)
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setenv("GIT_SHA", "abc123def")
    with (
        patch("bugsnag.configure") as configure_mock,
        patch.object(bugsnag.legacy.default_client, "notify") as notify_mock,
        patch.object(bugsnag.legacy.default_client, "notify_exc_info") as exc_info_mock,
    ):
        assert reporting.configure(settings) is True
        yield SimpleNamespace(
            configure=configure_mock, notify=notify_mock, notify_exc_info=exc_info_mock
        )
    reporting.reset_for_tests()


@pytest.fixture
def unconfigured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BUGSNAG_API_KEY", "")
    reporting.reset_for_tests()
    yield
    reporting.reset_for_tests()


@pytest.fixture
def probe_routes():
    """Throwaway routes on the real app, removed afterwards so route-enumerating
    tests (REST conventions, admin guard) never see them."""

    async def boom():
        raise RuntimeError("boom for bugsnag")

    async def http_502():
        try:
            raise ValueError("stripe down")
        except ValueError as e:
            raise HTTPException(status_code=502, detail="upstream down") from e

    async def http_400():
        raise HTTPException(status_code=400, detail="bad request")

    async def http_503_designed():
        raise HTTPException(status_code=503, detail="Please try again in a moment.")

    async def http_500_bare():
        raise HTTPException(status_code=500, detail="Failed to upload photo")

    async def upstream_unavailable():
        try:
            raise ValueError("stripe down")
        except ValueError as e:
            raise UpstreamUnavailable(detail="Payment service unavailable.") from e

    async def logged_then_bare_5xx():
        try:
            raise ValueError("s3 down")
        except ValueError:
            # A message-only log (no exc_info) then a cause-less 5xx in the same
            # except block: the 5xx is that failure's response, not a second one.
            logging.getLogger("tests.bugsnag").error("s3_upload_failed")
            # Deliberately no `from e` — the shape of a site that forgot it.
            raise HTTPException(status_code=503, detail="Please try again.")  # noqa: B904

    async def unrelated_log_then_5xx():
        logging.getLogger("tests.bugsnag").error("best_effort_lookup_failed")
        raise HTTPException(status_code=503, detail="Please try again.")

    async def logged_message_then_reraised():
        try:
            raise ValueError("s3 down")
        except ValueError:
            logging.getLogger("tests.bugsnag").error("s3_upload_failed")
            raise

    async def logged_then_raised():
        try:
            raise ValueError("s3 down")
        except ValueError as e:
            logging.getLogger("tests.bugsnag").exception("Failed to upload file to S3")
            raise HTTPException(status_code=500, detail="Failed to upload photo") from e

    async def new_error_after_logging():
        try:
            raise ValueError("stripe portal down")
        except ValueError:
            logging.getLogger("tests.bugsnag").exception("stripe_portal_open_failed")
            # A NEW failure; __context__ (not __cause__) is the ValueError.
            raise KeyError("template bug") from None

    added = [
        ("/__probe/new-error-after-logging", new_error_after_logging),
        ("/__probe/boom", boom),
        ("/__probe/http-502", http_502),
        ("/__probe/http-400", http_400),
        ("/__probe/http-503-designed", http_503_designed),
        ("/__probe/http-500-bare", http_500_bare),
        ("/__probe/logged-then-raised", logged_then_raised),
        ("/__probe/upstream-unavailable", upstream_unavailable),
        ("/__probe/logged-then-bare-5xx", logged_then_bare_5xx),
        ("/__probe/unrelated-log-then-5xx", unrelated_log_then_5xx),
        ("/__probe/logged-message-then-reraised", logged_message_then_reraised),
    ]
    for path, endpoint in added:
        app.add_api_route(path, endpoint, methods=["GET"])
    yield
    app.router.routes[:] = [
        r
        for r in app.router.routes
        if getattr(r, "path", None) not in {p for p, _ in added}
    ]


def _root_bugsnag_handlers() -> list[logging.Handler]:
    return [
        h
        for h in logging.getLogger().handlers
        if h.get_name() == reporting.HANDLER_NAME
    ]


class TestConfigure:
    def test_attaches_error_level_forwarder_and_release_config(self, configured):
        handlers = _root_bugsnag_handlers()
        assert len(handlers) == 1
        assert handlers[0].level == logging.ERROR
        assert reporting.is_configured() is True
        kwargs = configured.configure.call_args.kwargs
        assert kwargs["api_key"] == FAKE_KEY
        assert kwargs["release_stage"] == "staging"
        assert kwargs["app_version"] == "abc123def"
        assert set(kwargs["notify_release_stages"]) == {"production", "staging"}
        assert (
            "phone" in kwargs["params_filters"]
            and "phone_number" in kwargs["params_filters"]
        )

    def test_is_idempotent(self, configured):
        with patch("bugsnag.configure"):
            reporting.configure(settings)
        assert len(_root_bugsnag_handlers()) == 1

    def test_blank_key_is_a_no_op(self, unconfigured):
        assert reporting.configure(settings) is False
        assert _root_bugsnag_handlers() == []
        assert reporting.is_configured() is False
        assert reporting.notify(RuntimeError("x"), context="t") is False


class TestLogForwarding:
    def test_logger_error_reaches_bugsnag_with_extra_metadata(self, configured):
        logging.getLogger("tests.bugsnag").error(
            "worker phase failed: %s", "boom", extra={"session_id": "s-1"}
        )
        configured.notify.assert_called_once()
        exc, kwargs = (
            configured.notify.call_args.args[0],
            configured.notify.call_args.kwargs,
        )
        assert str(exc) == "worker phase failed: boom"
        assert kwargs["metadata"]["extra"]["session_id"] == "s-1"

    def test_logger_exception_carries_the_traceback(self, configured):
        try:
            raise ValueError("inner")
        except ValueError:
            logging.getLogger("tests.bugsnag").exception("caught")
        configured.notify_exc_info.assert_called_once()
        assert configured.notify_exc_info.call_args.args[0] is ValueError

    def test_info_and_warning_are_not_forwarded(self, configured):
        logging.getLogger("tests.bugsnag").warning("just a warning")
        logging.getLogger("tests.bugsnag").info("just info")
        configured.notify.assert_not_called()
        configured.notify_exc_info.assert_not_called()

    def test_error_report_skip_extra_prevents_a_duplicate(self, configured):
        logging.getLogger("tests.bugsnag").error(
            "already reported", extra={"error_report_skip": True}
        )
        configured.notify.assert_not_called()

    def test_message_only_records_group_by_logger_and_template(self, configured):
        # Without a stack every message-only record would share one "LogERROR"
        # group; the unformatted template keeps distinct alarms distinct.
        logging.getLogger("tests.bugsnag").error("Twilio failover for %s", "u-1")
        logging.getLogger("tests.bugsnag").error("Twilio failover for %s", "u-2")
        hashes = {c.kwargs["grouping_hash"] for c in configured.notify.call_args_list}
        assert hashes == {"tests.bugsnag:Twilio failover for %s"}

    def test_worker_phase_extra_becomes_the_event_context(self, configured):
        logging.getLogger("tests.bugsnag").error(
            "phase failed", extra={"phase": "outbox_send_due"}
        )
        assert configured.notify.call_args.kwargs["context"] == "outbox_send_due"

    def test_every_extra_key_is_forwarded_and_made_json_safe(self, configured):
        import uuid

        delivery_id = uuid.uuid4()
        logging.getLogger("tests.bugsnag").error(
            "stripe_customer_retry_failed",
            extra={
                "failed": 2,
                "delivery_id": delivery_id,
                "note": "sent to +14155551234",
            },
        )
        extra = configured.notify.call_args.kwargs["metadata"]["extra"]
        assert extra["failed"] == 2
        assert extra["delivery_id"] == str(delivery_id)  # not a bare UUID object
        assert extra["note"] == "sent to [PHONE]"
        assert "error_report_skip" not in extra

    def test_a_message_only_log_stamps_the_exception_being_handled(self, configured):
        # So a cause-less `raise HTTPException(5xx)` that follows in the same
        # except block (its __context__) is recognised as already reported.
        try:
            raise ValueError("s3 down")
        except ValueError as e:
            logging.getLogger("tests.bugsnag").error("s3_upload_failed")
            assert reporting.is_accounted_for(e)
            # ...but NOT reported: no traceback was sent, so a re-raise must
            # still produce the unhandled report.
            assert not reporting.was_forwarded(e)
        assert not reporting.is_accounted_for(ValueError("fresh"))


class FakeEvent:
    def __init__(self, message: str = "boom", context: str | None = None):
        self.user: dict = {}
        self.tabs: dict = {}
        self.errors = [SimpleNamespace(error_message=message)]
        self.context = context
        self.grouping_hash = None
        self.metadata: dict = {}
        self.breadcrumbs: list = []

    def set_user(self, id=None, **_):
        self.user["id"] = id

    def add_tab(self, name, data):
        self.tabs[name] = data
        self.metadata.setdefault(name, {}).update(data)


class TestRequestContext:
    def test_user_id_comes_from_the_auth_cookie_for_web_and_admin_requests(self):
        from unittest.mock import MagicMock

        from app.middleware.error_handler import _extract_user_id

        request = MagicMock()
        request.headers = {}
        request.cookies = {"access_token": create_access_token("admin-7")}
        assert _extract_user_id(request) == "admin-7"

    def test_phone_numbers_are_redacted_from_every_event_text(self):
        event = FakeEvent(
            message="Twilio: The 'To' number +14155551234 is not a valid phone number",
            context="sms +447700900123",
        )
        event.metadata = {"extra": {"note": "sent to +14155551234", "n": 2}}
        reporting._enrich_event(event)
        assert "+1415" not in event.errors[0].error_message
        assert "[PHONE]" in event.errors[0].error_message
        assert event.context == "sms [PHONE]"
        assert event.metadata["extra"] == {"note": "sent to [PHONE]", "n": 2}

    def test_breadcrumbs_are_scrubbed_before_they_are_recorded(self):
        # The SDK records every ERROR log as a process-wide breadcrumb before
        # before_notify runs, so a Twilio message would otherwise ride along on
        # the next event.
        crumb = SimpleNamespace(
            message="Twilio send failed to +14155551234",
            metadata={"to": "+14155551234", "attempt": 2},
        )
        reporting._scrub_breadcrumb(crumb)
        assert crumb.message == "Twilio send failed to [PHONE]"
        assert crumb.metadata == {"to": "[PHONE]", "attempt": 2}

    def test_before_notify_attaches_user_id_and_request(self):

        token = request_context_var.set(
            {"method": "POST", "path": "/api/v1/sessions", "user_id": "user-1"}
        )
        try:
            event = FakeEvent()
            reporting._enrich_event(event)
        finally:
            request_context_var.reset(token)
        assert event.user == {"id": "user-1"}
        assert event.tabs["request"]["method"] == "POST"
        assert event.tabs["request"]["path"] == "/api/v1/sessions"
        assert "request_id" in event.tabs["request"]


@pytest.mark.asyncio
class TestRequestPaths:
    async def test_unhandled_route_exception_is_reported_as_unhandled(
        self, client: AsyncClient, db_session, configured, probe_routes
    ):
        user = await create_test_user(db_session, phone_number="+14155599101")
        token = create_access_token(str(user.id))
        resp = await client.get(
            "/__probe/boom", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 500
        configured.notify.assert_called_once()
        exc, kwargs = (
            configured.notify.call_args.args[0],
            configured.notify.call_args.kwargs,
        )
        assert isinstance(exc, RuntimeError)
        assert kwargs["unhandled"] is True
        assert kwargs["context"] == "GET /__probe/boom"
        # Not clobbered by bugsnag.legacy.notify's "userSpecifiedSeverity".
        assert kwargs["severity_reason"]["type"] == "unhandledExceptionMiddleware"
        # The same exception must not ALSO arrive via the log forwarder.
        configured.notify_exc_info.assert_not_called()

    async def test_http_5xx_reports_the_cause_and_4xx_does_not(
        self, client: AsyncClient, configured, probe_routes
    ):
        resp = await client.get("/__probe/http-502")
        assert resp.status_code == 502
        assert resp.json() == {"detail": "upstream down"}
        configured.notify.assert_called_once()
        exc, kwargs = (
            configured.notify.call_args.args[0],
            configured.notify.call_args.kwargs,
        )
        assert isinstance(exc, ValueError)  # the `from e` cause, not the HTTPException
        assert kwargs["metadata"]["http"]["status_code"] == 502
        assert kwargs.get("unhandled") is not True

        resp = await client.get("/__probe/http-400")
        assert resp.status_code == 400
        configured.notify.assert_called_once()  # unchanged: 4xx is not an error

    async def test_every_plain_5xx_is_an_error_whatever_its_status(
        self, client: AsyncClient, configured, probe_routes
    ):
        # Only UpstreamUnavailable is a warning: a cause-less 503 (a fail-closed
        # "secret misconfigured" response) is a defect exactly like a bare 500.
        assert (await client.get("/__probe/http-503-designed")).status_code == 503
        configured.notify.assert_called_once()
        assert configured.notify.call_args.kwargs["severity"] == "error"
        configured.notify.reset_mock()
        assert (await client.get("/__probe/http-500-bare")).status_code == 500
        configured.notify.assert_called_once()
        assert configured.notify.call_args.kwargs["severity"] == "error"

    async def test_designed_upstream_failure_is_a_warning_with_its_cause(
        self, client: AsyncClient, configured, probe_routes
    ):
        # A provider outage the endpoint is designed to translate (UpstreamUnavailable
        # from a StripeError) is not a defect: warning severity, provider's stack.
        assert (await client.get("/__probe/upstream-unavailable")).status_code == 502
        configured.notify.assert_called_once()
        assert configured.notify.call_args.kwargs["severity"] == "warning"
        assert isinstance(configured.notify.call_args.args[0], ValueError)

    async def test_a_new_exception_raised_after_logging_is_still_reported(
        self, client: AsyncClient, configured, probe_routes
    ):
        # `logger.exception` stamped the StripeError; the render bug raised
        # afterwards carries it only as __context__ and must NOT be deduped.
        resp = await client.get("/__probe/new-error-after-logging")
        assert resp.status_code == 500
        configured.notify_exc_info.assert_called_once()  # the logged one
        configured.notify.assert_called_once()  # the new, unhandled one
        assert isinstance(configured.notify.call_args.args[0], KeyError)

    async def test_logged_then_raised_exception_reports_exactly_once(
        self, client: AsyncClient, configured, probe_routes
    ):
        # logger.exception forwards it (with exc_info); the 5xx handler then sees
        # an HTTPException raised `from` the same exception and dedupes.
        assert (await client.get("/__probe/logged-then-raised")).status_code == 500
        configured.notify_exc_info.assert_called_once()
        configured.notify.assert_not_called()

    async def test_message_log_then_bare_5xx_in_the_same_block_reports_once(
        self, client: AsyncClient, configured, probe_routes
    ):
        assert (await client.get("/__probe/logged-then-bare-5xx")).status_code == 503
        configured.notify.assert_called_once()  # the log; the 503 is its response
        assert str(configured.notify.call_args.args[0]) == "s3_upload_failed"

    async def test_a_5xx_after_an_unrelated_error_log_is_its_own_report(
        self, client: AsyncClient, configured, probe_routes
    ):
        assert (await client.get("/__probe/unrelated-log-then-5xx")).status_code == 503
        assert configured.notify.call_count == 2
        assert configured.notify.call_args.kwargs["severity"] == "error"

    async def test_a_message_log_never_suppresses_the_unhandled_report(
        self, client: AsyncClient, configured, probe_routes
    ):
        # `logger.error("...")` (no exc_info) then `raise`: the message-only
        # event has no traceback, so the unhandled report is still due.
        resp = await client.get("/__probe/logged-message-then-reraised")
        assert resp.status_code == 500
        assert configured.notify.call_count == 2
        assert configured.notify.call_args.kwargs.get("unhandled") is True

    async def test_worker_safe_wrapper_forwards_the_exception(self, configured):
        from worker_tick import _safe

        errors: list[str] = []
        async with _safe("outbox_send_due", errors):
            raise ValueError("provider down")
        assert errors == ["outbox_send_due: provider down"]
        configured.notify_exc_info.assert_called_once()
        assert configured.notify_exc_info.call_args.args[0] is ValueError


class TestStartupCheck:
    def test_worker_entrypoints_run_the_startup_checks_too(self):
        root = Path(__file__).resolve().parent.parent
        for entry in ("worker_loop.py", "worker_tick.py"):
            assert (
                "run_production_startup_checks(settings)" in (root / entry).read_text()
            ), entry

    def test_refuses_to_boot_without_a_key_in_production(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "BUGSNAG_API_KEY", "")
        with pytest.raises(RuntimeError, match="BUGSNAG_API_KEY"):
            _check_error_reporting(settings)

    def test_passes_with_a_key(self, monkeypatch):
        monkeypatch.setattr(settings, "BUGSNAG_API_KEY", FAKE_KEY)
        _check_error_reporting(settings)

    def test_is_part_of_the_production_startup_checks(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        with (
            patch("app.core.startup_checks._check_sms_backend") as sms,
            patch("app.core.startup_checks._check_error_reporting") as bugsnag_check,
        ):
            run_production_startup_checks(settings)
        sms.assert_called_once()
        bugsnag_check.assert_called_once()

    def test_is_skipped_outside_staging_and_production(self, monkeypatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        with patch("app.core.startup_checks._check_error_reporting") as bugsnag_check:
            run_production_startup_checks(settings)
        bugsnag_check.assert_not_called()


@pytest.mark.asyncio
class TestHealthAndSmoke:
    async def test_health_reports_version_and_bugsnag_state(
        self, client: AsyncClient, configured
    ):
        assert (await client.get("/health")).json()["version"] == "abc123def"
        ready = await client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json()["checks"]["error_reporting"] == "configured"

        reporting.reset_for_tests()
        ready = await client.get("/health/ready")
        assert ready.status_code == 200  # informational only — never flips readiness
        assert ready.json()["checks"]["error_reporting"] == "unconfigured"

    async def test_admin_smoke_button_sends_a_test_event(
        self, client: AsyncClient, admin_cookies: dict, configured
    ):
        token = generate_csrf_token()
        resp = await client.post(
            "/admin/error-reporting-test",
            cookies={**admin_cookies, CSRF_COOKIE_NAME: token},
            data={CSRF_FORM_FIELD: token},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/?error_reporting_test=sent"
        configured.notify.assert_called_once()
        exc, kwargs = (
            configured.notify.call_args.args[0],
            configured.notify.call_args.kwargs,
        )
        assert isinstance(exc, reporting.ErrorReportingSmokeTestError)
        assert kwargs["severity"] == "info"
        assert kwargs["context"] == "admin.error-reporting-test"

    async def test_admin_smoke_button_reports_unconfigured(
        self, client: AsyncClient, admin_cookies: dict, unconfigured
    ):
        token = generate_csrf_token()
        resp = await client.post(
            "/admin/error-reporting-test",
            cookies={**admin_cookies, CSRF_COOKIE_NAME: token},
            data={CSRF_FORM_FIELD: token},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/?error_reporting_test=unconfigured"

    async def test_dashboard_renders_the_error_reporting_panel(
        self, client: AsyncClient, admin_cookies: dict
    ):
        resp = await client.get(
            "/admin/?error_reporting_test=sent", cookies=admin_cookies
        )
        assert resp.status_code == 200
        assert "Send error-reporting test event" in resp.text
        assert "Test event sent" in resp.text
