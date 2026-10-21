"""init_error_reporting configures Bugsnag (incl. release_stage) for any entrypoint.

Regression: the worker process (worker_tick.py) calls bugsnag.notify() but never
imports app.main, so Bugsnag was unconfigured there and its events (including the
stuck-session alert that signals undelivered safety alerts) were silently
dropped. init_error_reporting — called by setup_logging, which both the web app and the
worker invoke — fixes that, and sets release_stage from ENVIRONMENT.
"""

from unittest.mock import patch

import pytest

from app.core import error_reporting
from app.core.config import settings
from app.core.logging import init_error_reporting


@pytest.fixture(autouse=True)
def _detach_forwarder():
    # init_error_reporting attaches the root-logger forwarder; never leave it behind
    # for later tests (it would try to deliver their logger.error calls).
    yield
    error_reporting.reset_for_tests()


def test_init_error_reporting_sets_release_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BUGSNAG_API_KEY", "test-key")
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    with patch("bugsnag.configure") as mock_configure:
        init_error_reporting()
    mock_configure.assert_called_once()
    kwargs = mock_configure.call_args.kwargs
    assert kwargs["release_stage"] == "staging"
    assert kwargs["api_key"] == "test-key"
    assert "staging" in kwargs["notify_release_stages"]


def test_init_error_reporting_noop_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "BUGSNAG_API_KEY", "")
    with patch("bugsnag.configure") as mock_configure:
        init_error_reporting()
    mock_configure.assert_not_called()
