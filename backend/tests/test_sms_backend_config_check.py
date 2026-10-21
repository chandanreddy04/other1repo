"""Tests for the staging/prod startup check + runtime fail-loud.

Catches the "Twilio creds rotated to invalid and nobody noticed because
the deploy looked healthy" failure mode.
"""

import pytest

from app.core.startup_checks import run_production_startup_checks
from app.services.sms import SMSResult, _TwilioBackend


def _twilio_unconfigured(monkeypatch) -> None:
    """Force the Twilio backend into its unconfigured state for the
    test duration without touching the live env or relying on import
    ordering."""
    from app.services import sms

    monkeypatch.setattr(sms.settings, "TWILIO_ACCOUNT_SID", "")
    monkeypatch.setattr(sms.settings, "TWILIO_AUTH_TOKEN", "")


def test_validate_sms_backend_noop_in_development(monkeypatch) -> None:
    from app.services import sms

    monkeypatch.setattr(sms.settings, "ENVIRONMENT", "development")
    _twilio_unconfigured(monkeypatch)
    # Should not raise even if no SMS backend is configured — dev mode
    # is allowed to console-print.
    run_production_startup_checks(sms.settings)


def test_validate_sms_backend_raises_in_production_when_unconfigured(
    monkeypatch,
) -> None:
    from app.services import sms

    monkeypatch.setattr(sms.settings, "ENVIRONMENT", "production")
    # Patch the live `sms_service` singleton so the validator sees an
    # unconfigured backend pair.
    monkeypatch.setattr(sms.sms_service.twilio, "client", None)
    monkeypatch.setattr(sms.sms_service.failover, "client", None)
    with pytest.raises(RuntimeError, match="SMS backend not configured"):
        run_production_startup_checks(sms.settings)


def test_validate_sms_backend_accepts_failover_only_in_production(
    monkeypatch,
) -> None:
    """A failover-only configuration is acceptable — Twilio doesn't
    have to be primary."""
    from app.services import sms

    monkeypatch.setattr(sms.settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(sms.sms_service.twilio, "client", None)
    # Production boot also requires error reporting (startup_checks._check_error_reporting).
    monkeypatch.setattr(
        sms.settings, "BUGSNAG_API_KEY", "0123456789abcdef0123456789abcdef"
    )

    class _FakeOk:
        configured = True

    monkeypatch.setattr(sms.sms_service, "failover", _FakeOk())
    run_production_startup_checks(sms.settings)


@pytest.mark.asyncio
async def test_twilio_send_in_dev_returns_success_when_unconfigured(
    monkeypatch,
) -> None:
    from app.services import sms

    monkeypatch.setattr(sms.settings, "ENVIRONMENT", "development")
    backend = _TwilioBackend()
    backend.client = None  # force unconfigured
    result: SMSResult = await backend.send_sms("+14155550100", "hello")
    assert result.success is True
    assert result.error is None


@pytest.mark.asyncio
async def test_twilio_send_in_prod_returns_failure_when_unconfigured(
    monkeypatch,
) -> None:
    from app.services import sms

    monkeypatch.setattr(sms.settings, "ENVIRONMENT", "production")
    backend = _TwilioBackend()
    backend.client = None
    result = await backend.send_sms("+14155550101", "hello")
    assert result.success is False
    assert result.error == "twilio_not_configured"
