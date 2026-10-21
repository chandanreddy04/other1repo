"""Tests for SMS service Twilio→failover orchestration.

The failover provider is SNS (AWS SNS is the only supported value). These
tests exercise the ORCHESTRATION in `SMSService.send_sms`
with mocked backends; the SNS backend itself is covered in test_sms_sns.py
and the Twilio backend below.
"""
from unittest.mock import MagicMock

import pytest
from twilio.base.exceptions import TwilioException

from app.models.alert import SMSProvider
from app.services.sms import SMSResult, SMSService


def _make_service(
    twilio_send=None,
    failover_send=None,
    *,
    twilio_configured: bool = True,
    failover_configured: bool = True,
) -> SMSService:
    svc = SMSService.__new__(SMSService)

    twilio_backend = MagicMock()
    twilio_backend.configured = twilio_configured
    twilio_backend.send_sms = twilio_send or MagicMock()
    twilio_backend.provider_enum = SMSProvider.TWILIO
    svc.twilio = twilio_backend

    failover_backend = MagicMock()
    failover_backend.configured = failover_configured
    failover_backend.send_sms = failover_send or MagicMock()
    failover_backend.provider_enum = SMSProvider.SNS
    svc.failover = failover_backend

    return svc


@pytest.mark.asyncio
class TestSMSFailover:
    async def test_twilio_success_does_not_use_failover(self):
        async def twilio_send(*a, **kw):
            return SMSResult(
                success=True, message_id="SM1", provider=SMSProvider.TWILIO
            )

        async def failover_send(*a, **kw):
            raise AssertionError("failover should not be called when Twilio succeeds")

        svc = _make_service(twilio_send=twilio_send, failover_send=failover_send)
        result = await svc.send_sms("+14155550100", "hello")
        assert result.success is True
        assert result.provider == SMSProvider.TWILIO

    async def test_twilio_failure_falls_over_to_sns(self):
        async def twilio_send(*a, **kw):
            return SMSResult(
                success=False, error="Twilio API down", provider=SMSProvider.TWILIO
            )

        async def failover_send(*a, **kw):
            return SMSResult(
                success=True, message_id="SNS1", provider=SMSProvider.SNS
            )

        svc = _make_service(twilio_send=twilio_send, failover_send=failover_send)
        result = await svc.send_sms("+14155550101", "hi")
        assert result.success is True
        assert result.provider == SMSProvider.SNS
        assert result.message_id == "SNS1"

    async def test_both_fail_returns_twilio_error(self):
        async def twilio_send(*a, **kw):
            return SMSResult(
                success=False, error="Twilio down", provider=SMSProvider.TWILIO
            )

        async def failover_send(*a, **kw):
            return SMSResult(
                success=False, error="SNS down too", provider=SMSProvider.SNS
            )

        svc = _make_service(twilio_send=twilio_send, failover_send=failover_send)
        result = await svc.send_sms("+14155550102", "hi")
        assert result.success is False
        # Original Twilio error returned (so the cron knows to retry later)
        assert result.provider == SMSProvider.TWILIO
        assert "Twilio down" in result.error

    async def test_explicit_sns_provider_skips_twilio(self):
        async def twilio_send(*a, **kw):
            raise AssertionError("Twilio should not be called when provider=SNS")

        async def failover_send(*a, **kw):
            return SMSResult(
                success=True, message_id="SNS_R", provider=SMSProvider.SNS
            )

        svc = _make_service(twilio_send=twilio_send, failover_send=failover_send)
        result = await svc.send_sms(
            "+14155550103", "retry msg", provider=SMSProvider.SNS
        )
        assert result.success is True
        assert result.provider == SMSProvider.SNS

    async def test_explicit_twilio_provider_skips_failover(self):
        async def twilio_send(*a, **kw):
            return SMSResult(
                success=True, message_id="SM_R", provider=SMSProvider.TWILIO
            )

        async def failover_send(*a, **kw):
            raise AssertionError("failover should not be called when provider=TWILIO")

        svc = _make_service(twilio_send=twilio_send, failover_send=failover_send)
        result = await svc.send_sms(
            "+14155550104", "retry", provider=SMSProvider.TWILIO
        )
        assert result.success is True
        assert result.provider == SMSProvider.TWILIO

    async def test_retry_for_stale_provider_routes_to_active_failover(self):
        """If a retry comes in for a failover provider that's no longer the
        active failover (the provider changed between the original send and
        the retry), we route through the active failover rather than
        synthesizing a failure — delivery matters more than per-message
        webhook routing fidelity for the retry.

        Simulated by giving the failover backend a provider_enum that
        doesn't match the retry's requested provider (TWILIO stand-in).
        """
        async def twilio_send(*a, **kw):
            raise AssertionError("Twilio should not be called for a failover retry")

        async def failover_send(*a, **kw):
            return SMSResult(
                success=True, message_id="X_R", provider=SMSProvider.TWILIO
            )

        svc = _make_service(twilio_send=twilio_send, failover_send=failover_send)
        # Stale: alert in DB says SNS, but the active failover identifies
        # as a different provider.
        svc.failover.provider_enum = SMSProvider.TWILIO

        result = await svc.send_sms(
            "+14155550105", "retry", provider=SMSProvider.SNS
        )
        assert result.success is True
        # Routed through the active failover, which reports its own provider.
        assert result.provider == SMSProvider.TWILIO


@pytest.mark.asyncio
class TestTwilioBackend:
    async def test_unconfigured_returns_dev_success(self):
        from app.services.sms import _TwilioBackend

        backend = _TwilioBackend.__new__(_TwilioBackend)
        backend.client = None
        result = await backend.send_sms("+14155550110", "hi")
        assert result.success is True
        assert result.provider == SMSProvider.TWILIO

    async def test_twilio_exception_returns_failure(self):
        from app.services.sms import _TwilioBackend

        backend = _TwilioBackend.__new__(_TwilioBackend)
        client = MagicMock()
        client.messages.create.side_effect = TwilioException("network blew up")
        backend.client = client

        result = await backend.send_sms("+14155550111", "hi")
        assert result.success is False
        assert result.provider == SMSProvider.TWILIO
        assert "network" in result.error
