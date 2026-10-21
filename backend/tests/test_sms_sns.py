"""Tests for the AWS SNS SMS failover backend (`sms_sns._SNSBackend`).

Uses moto to mock SNS end-to-end (real boto3 → in-memory SNS), catching
API misuse that pure mocks miss. Selected by SMS_FAILOVER_PROVIDER=sns.
"""

from unittest.mock import patch

import pytest
from moto import mock_aws

from app.models.alert import SMSProvider

REGION = "us-west-2"


def _set_sns_env(monkeypatch):
    monkeypatch.setattr("app.services.sms_sns.settings.AWS_SNS_REGION", REGION)
    monkeypatch.setattr("app.services.sms_sns.settings.AWS_SNS_SENDER_ID", "")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.mark.asyncio
class TestSNSBackend:
    async def test_init_without_region_degrades_unconfigured(self, monkeypatch):
        """SNS is the default failover: a boot without AWS env must not
        crash — it degrades to configured=False and sends report failure
        (behavior changed 2026-07-02 when SNS became the default)."""
        monkeypatch.setattr("app.services.sms_sns.settings.AWS_SNS_REGION", "")
        monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
        from app.services.sms_sns import _SNSBackend

        backend = _SNSBackend()
        assert backend.configured is False
        result = await backend.send_sms("+14155550130", "hi")
        assert result.success is False

    async def test_init_falls_back_to_aws_default_region(self, monkeypatch):
        monkeypatch.setattr("app.services.sms_sns.settings.AWS_SNS_REGION", "")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        from app.services.sms_sns import _SNSBackend

        backend = _SNSBackend()
        assert backend.region == "us-east-1"

    async def test_send_sms_success(self, monkeypatch):
        _set_sns_env(monkeypatch)
        with mock_aws():
            from app.services.sms_sns import _SNSBackend

            backend = _SNSBackend()
            result = await backend.send_sms("+14155550100", "hello world")

            assert result.success is True
            # Real SNS returns a UUID-shaped string; tightened from truthy.
            assert result.message_id is not None and len(result.message_id) > 10
            assert result.provider == SMSProvider.SNS
            assert result.error is None

    async def test_send_sms_with_sender_id(self, monkeypatch):
        _set_sns_env(monkeypatch)
        monkeypatch.setattr(
            "app.services.sms_sns.settings.AWS_SNS_SENDER_ID", "MadeItHome"
        )
        with mock_aws():
            from app.services.sms_sns import _SNSBackend

            backend = _SNSBackend()
            result = await backend.send_sms("+14155550101", "alert!")

            assert result.success is True
            assert result.provider == SMSProvider.SNS

    async def test_send_sms_client_error_returns_failure(self, monkeypatch):
        _set_sns_env(monkeypatch)
        with mock_aws():
            from app.services.sms_sns import _SNSBackend

            backend = _SNSBackend()
            # Invalid phone format — SNS rejects with InvalidParameter.
            result = await backend.send_sms("not-a-phone", "x")

            assert result.success is False
            assert result.provider == SMSProvider.SNS
            assert result.error  # error string populated

    async def test_send_sms_marks_as_transactional(self, monkeypatch):
        """Safety alerts must use Transactional pricing/priority, never
        Promotional (which is delayed and lower delivery rate)."""
        _set_sns_env(monkeypatch)
        with mock_aws():
            from app.services.sms_sns import _SNSBackend

            backend = _SNSBackend()
            real_publish = backend.client.publish

            # patch.object auto-restores after the with-block — safer than
            # mutating `backend.client.publish` directly under parallel runs.
            with patch.object(
                backend.client, "publish", side_effect=real_publish
            ) as spy:
                await backend.send_sms("+14155550102", "ok")

            attrs = spy.call_args.kwargs["MessageAttributes"]
            assert attrs["AWS.SNS.SMS.SMSType"]["StringValue"] == "Transactional"


@pytest.mark.asyncio
class TestSNSViaFactory:
    """End-to-end: setting SMS_FAILOVER_PROVIDER=sns returns _SNSBackend
    through the SMSService factory."""

    async def test_factory_returns_sns_backend(self, monkeypatch):
        _set_sns_env(monkeypatch)
        with mock_aws():
            from app.services import sms
            from app.services.sms_sns import _SNSBackend

            monkeypatch.setattr(sms.settings, "SMS_FAILOVER_PROVIDER", "sns")
            backend = sms._make_failover_backend()

            assert isinstance(backend, _SNSBackend)
            assert backend.provider_enum == SMSProvider.SNS


@pytest.mark.asyncio
class TestSNSInSMSService:
    """When the failover is SNS, SMSService falls over from Twilio to SNS
    on Twilio failure."""

    async def test_twilio_failure_falls_over_to_sns(self, monkeypatch):
        _set_sns_env(monkeypatch)
        with mock_aws():
            from app.services import sms
            from app.services.sms import SMSResult, SMSService

            monkeypatch.setattr(sms.settings, "SMS_FAILOVER_PROVIDER", "sns")
            monkeypatch.setattr(sms.settings, "TWILIO_ACCOUNT_SID", "")
            monkeypatch.setattr(sms.settings, "TWILIO_AUTH_TOKEN", "")

            service = SMSService()

            async def failing_twilio(to_phone, message):
                return SMSResult(
                    success=False,
                    error="Twilio outage",
                    provider=SMSProvider.TWILIO,
                )

            service.twilio.send_sms = failing_twilio

            result = await service.send_sms("+14155550200", "fall over")

            assert result.success is True
            assert result.provider == SMSProvider.SNS

    async def test_unknown_phone_format_does_not_silently_succeed(self, monkeypatch):
        """If failover also fails (Twilio is mocked to fail; SNS rejects the
        bad phone format), the orchestrator returns the *Twilio* error per
        the existing contract — that's what the cron worker sees and retries
        against, so preserving the primary's error is the right behavior."""
        _set_sns_env(monkeypatch)
        with mock_aws():
            from app.services import sms
            from app.services.sms import SMSResult, SMSService

            monkeypatch.setattr(sms.settings, "SMS_FAILOVER_PROVIDER", "sns")

            service = SMSService()

            async def failing_twilio(to_phone, message):
                return SMSResult(
                    success=False,
                    error="Twilio rejected",
                    provider=SMSProvider.TWILIO,
                )

            service.twilio.send_sms = failing_twilio

            result = await service.send_sms("not-a-phone", "x")

            assert result.success is False
            # Twilio error preserved (so the cron worker retries via the
            # original provider's path; both failed so retry is correct).
            assert result.provider == SMSProvider.TWILIO
            assert "Twilio rejected" in (result.error or "")
