"""SMS service with Twilio primary and AWS SNS failover.

`SMSService.send_sms` tries Twilio first; on failure, falls back to the
failover provider selected by `SMS_FAILOVER_PROVIDER` (`sns`, AWS SNS, is
the only supported value). The result records which provider sent the
message so retries (handled by the
cron worker) route through the same provider — important when the
provider's delivery webhook is the source of truth for delivery state.

Related: services/session_tasks.py (consumers),
         api/v1/endpoints/delivery_webhooks.py (delivery callbacks),
         services/sms_sns.py (SNS failover backend).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from twilio.base.exceptions import TwilioException
from twilio.rest import Client

from app.core.config import settings
from app.models.alert import SMSProvider
from app.utils.phone import phone_tag

logger = logging.getLogger(__name__)


@dataclass
class SMSResult:
    success: bool
    message_id: str | None = None
    error: str | None = None
    provider: SMSProvider | None = None


class SMSBackend(Protocol):
    """A single SMS provider — knows its enum value, whether it's configured,
    and how to send. Used uniformly for Twilio (primary) and failover providers.

    Not `@runtime_checkable` because Python 3.12 forbids isinstance/issubclass
    on Protocols with non-method members (like `provider_enum`). Interface
    conformance is enforced at the `_FAILOVER_BACKENDS` dispatch dict (mypy
    catches a backend missing required members when it's registered there).
    """

    provider_enum: SMSProvider

    @property
    def configured(self) -> bool: ...

    async def send_sms(self, to_phone: str, message: str) -> SMSResult: ...


class _TwilioBackend:
    """Wraps the Twilio REST client and exposes a single send_sms method."""

    # Class attribute (not Final — Protocol declares it as mutable; mypy
    # rejects Final-vs-non-Final mismatch when matching against SMSBackend).
    provider_enum: SMSProvider = SMSProvider.TWILIO

    def __init__(self) -> None:
        self.client: Client | None = None
        if (
            settings.TWILIO_ACCOUNT_SID
            and settings.TWILIO_AUTH_TOKEN
            and settings.TWILIO_ACCOUNT_SID != "your-account-sid"
            and settings.TWILIO_AUTH_TOKEN != "your-auth-token"
        ):
            try:
                self.client = Client(
                    settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
                )
            except Exception:
                logger.exception("Failed to initialize Twilio client")

    @property
    def configured(self) -> bool:
        return self.client is not None

    async def send_sms(self, to_phone: str, message: str) -> SMSResult:
        if not self.client:
            # In dev/test, console-print the SMS as a stand-in for
            # delivery. This is how OTPs become observable without
            # real Twilio creds and is intentional per CLAUDE.md;
            # test fixtures also rely on the silent-success path
            # rather than wiring real Twilio.
            #
            # In staging/prod, an unconfigured Twilio client is a
            # misconfigured deploy — return success=False so callers
            # don't silently report sent. The startup check in
            # app.main.lifespan should normally catch this earlier,
            # but if creds get rotated to invalid mid-deploy, this is
            # the runtime safety net.
            if settings.ENVIRONMENT in ("development", "test"):
                logger.info("[DEV] SMS to %s: %s", to_phone, message)
                return SMSResult(success=True, provider=SMSProvider.TWILIO)
            logger.error(
                "twilio_not_configured_at_send_time",
                extra={"environment": settings.ENVIRONMENT},
            )
            return SMSResult(
                success=False,
                error="twilio_not_configured",
                provider=SMSProvider.TWILIO,
            )
        try:
            msg = self.client.messages.create(
                body=message, from_=settings.TWILIO_PHONE_NUMBER, to=to_phone
            )
            logger.info("Twilio SMS sent: %s", msg.sid)
            return SMSResult(
                success=True, message_id=msg.sid, provider=SMSProvider.TWILIO
            )
        except TwilioException as e:
            logger.exception("Twilio error sending SMS to %s", phone_tag(to_phone))
            return SMSResult(success=False, error=str(e), provider=SMSProvider.TWILIO)


def _make_sns_backend() -> SMSBackend:
    # Lazy import keeps boto3 off the import path until first use.
    from app.services.sms_sns import _SNSBackend

    return _SNSBackend()


# Single source of truth for failover providers.
_FAILOVER_BACKENDS: dict[str, Callable[[], SMSBackend]] = {
    "sns": _make_sns_backend,
}


def _make_failover_backend() -> SMSBackend:
    """Pick the failover SMS backend based on `settings.SMS_FAILOVER_PROVIDER`.

    Env value is lowercased so case mismatches don't silently fall through.
    """
    name = settings.SMS_FAILOVER_PROVIDER.lower()
    factory = _FAILOVER_BACKENDS.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown SMS_FAILOVER_PROVIDER: {name!r} "
            f"(supported: {sorted(_FAILOVER_BACKENDS)})"
        )
    return factory()


class SMSService:
    """Twilio-first SMS service with a pluggable failover provider.

    Class is also the seam for cross-cutting concerns (metrics, retries,
    request-id propagation) that should apply to every provider uniformly.
    """

    def __init__(self) -> None:
        self.twilio = _TwilioBackend()
        self.failover: SMSBackend = _make_failover_backend()

    async def send_sms(
        self,
        to_phone: str,
        message: str,
        *,
        provider: SMSProvider | None = None,
    ) -> SMSResult:
        """Send SMS. If `provider` is given, route through that specific
        provider (used for retries — historically required to match the
        original sender so the delivery webhook resolved to the right Alert).

        Cross-cloud robustness: if `provider` names a failover provider that
        differs from the currently-active failover (e.g. the failover provider
        changed between the original send and the retry), we route
        through the active failover and log a warning. Getting the message
        delivered matters more than preserving the original provider — the
        downside is that the retry's delivery receipt will arrive via the
        new provider's webhook, which the retry record may not be expecting.
        That's a soft data-quality issue, not a delivery failure.
        """
        if provider == SMSProvider.TWILIO:
            return await self.twilio.send_sms(to_phone, message)
        if provider is not None and provider != self.failover.provider_enum:
            logger.warning(
                "SMS retry requested provider %s but active failover is %s — "
                "routing through active failover anyway",
                provider,
                self.failover.provider_enum,
            )
        if provider is not None:
            return await self.failover.send_sms(to_phone, message)

        result = await self.twilio.send_sms(to_phone, message)
        if result.success:
            return result
        # WARNING: the Twilio backend already reported its exception with a
        # stack; a second ERROR here would double every failed attempt.
        logger.warning(
            "Twilio send failed (%s); failing over to %s",
            result.error,
            self.failover.provider_enum.value,
        )
        failover_result = await self.failover.send_sms(to_phone, message)
        return failover_result if failover_result.success else result


sms_service = SMSService()
