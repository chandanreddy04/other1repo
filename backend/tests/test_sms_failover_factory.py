"""Tests for the SMS failover backend factory.

The factory (`_make_failover_backend`) lets a deploy pick its failover
provider via `SMS_FAILOVER_PROVIDER`. SNS (AWS SNS) is the only supported
provider. Tests
for the orchestrator (`SMSService`) live in
test_notification_reliability_sms.py.
"""

import pytest

from app.services import sms
from app.services.sms import (
    SMSService,
    _make_failover_backend,
)
from app.services.sms_sns import _SNSBackend


class TestSMSFailoverFactory:
    def test_default_failover_is_sns(self, monkeypatch):
        monkeypatch.setattr(sms.settings, "SMS_FAILOVER_PROVIDER", "sns")
        monkeypatch.setattr(sms.settings, "AWS_SNS_REGION", "")

        backend = _make_failover_backend()

        assert isinstance(backend, _SNSBackend)

    def test_env_var_is_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(sms.settings, "SMS_FAILOVER_PROVIDER", "SNS")
        monkeypatch.setattr(sms.settings, "AWS_SNS_REGION", "")

        backend = _make_failover_backend()

        assert isinstance(backend, _SNSBackend)

    def test_unknown_failover_raises_value_error(self, monkeypatch):
        monkeypatch.setattr(sms.settings, "SMS_FAILOVER_PROVIDER", "wat")

        with pytest.raises(ValueError, match="Unknown SMS_FAILOVER_PROVIDER"):
            _make_failover_backend()


class TestBackendInterfaceShape:
    """SMSBackend is a Protocol with non-method members (`provider_enum`),
    which Python 3.12 forbids for runtime issubclass — mypy is the only line
    of defense for interface conformance. These tests verify the bits that
    SMSService.send_sms relies on at runtime are actually present."""

    def test_twilio_has_required_attributes(self):
        from app.services.sms import _TwilioBackend

        assert hasattr(_TwilioBackend, "provider_enum")
        assert callable(_TwilioBackend.send_sms)
        assert isinstance(_TwilioBackend.configured, property)

    def test_sns_has_required_attributes(self):
        assert hasattr(_SNSBackend, "provider_enum")
        assert callable(_SNSBackend.send_sms)
        assert isinstance(_SNSBackend.configured, property)


class TestSMSServiceWiresFailover:
    def test_init_uses_active_failover(self, monkeypatch):
        """SMSService picks up whatever failover the factory returns —
        and boots cleanly when SNS is unconfigured (no AWS region)."""
        monkeypatch.setattr(sms.settings, "SMS_FAILOVER_PROVIDER", "sns")
        monkeypatch.setattr(sms.settings, "AWS_SNS_REGION", "")
        monkeypatch.setattr(sms.settings, "TWILIO_ACCOUNT_SID", "")
        monkeypatch.setattr(sms.settings, "TWILIO_AUTH_TOKEN", "")
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

        service = SMSService()

        assert isinstance(service.failover, _SNSBackend)
        assert service.failover.configured is False
