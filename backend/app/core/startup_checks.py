"""Production-only startup validations.

Run once at app boot via `app.main.lifespan`. If we're in staging or
production and any required external dependency is misconfigured,
raise — failing at boot is better than acknowledging requests that
will silently drop OTPs, alerts, or payments.

Dev/test environments skip every check; the placeholder configs are
intentional (OTPs print to console, Stripe is mocked, etc.).

Add a new check here when introducing a deploy-time prerequisite:

    def _check_redis(settings: Settings) -> None:
        if not settings.REDIS_URL:
            raise RuntimeError("REDIS_URL must be set in staging/production")

    def run_production_startup_checks(settings: Settings) -> None:
        ...
        _check_redis(settings)

The single-module / single-entry-point shape (no decorator-based
registration) keeps the boot order obvious — every check is visible
in `run_production_startup_checks`, and grepping for it shows what
runs at startup.
"""

import logging

from app.core.config import Settings

logger = logging.getLogger(__name__)


def run_production_startup_checks(settings: Settings) -> None:
    """Run every startup check that applies to the current environment.

    No-op outside staging/production: dev/test deliberately tolerate
    placeholder config so the app boots without secrets.
    """
    if settings.ENVIRONMENT not in ("staging", "production"):
        return
    _check_sms_backend(settings)
    _check_error_reporting(settings)
    # Add new checks below as the deploy prerequisites grow.


def _check_sms_backend(settings: Settings) -> None:
    """Refuse to start without a working SMS backend.

    Without SMS we silently lose: OTP delivery, circle alerts, sponsor
    magic links, sub-lapse warnings — every user-facing flow that
    matters. Pre-deploy creds are easy to forget; better to fail at
    boot than to look healthy and silently drop messages.
    """
    from app.services.sms import sms_service

    twilio_ok = sms_service.twilio.configured
    failover_ok = sms_service.failover.configured
    if not (twilio_ok or failover_ok):
        raise RuntimeError(
            f"SMS backend not configured for ENVIRONMENT={settings.ENVIRONMENT}. "
            "Set TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN, or provision an "
            "SMS_FAILOVER_PROVIDER (sns). Refusing to start so a "
            "misconfigured deploy doesn't silently drop OTPs and alerts."
        )


def _check_error_reporting(settings: Settings) -> None:
    """Refuse to start without error reporting.

    A blank BUGSNAG_API_KEY used to be a silent no-op — the app ran blind for
    months and nobody could tell "no errors" from "no reporting". Same posture
    as the SMS check: a misconfigured deploy fails at the health check instead
    of looking healthy.
    """
    if not settings.BUGSNAG_API_KEY:
        raise RuntimeError(
            f"BUGSNAG_API_KEY is blank for ENVIRONMENT={settings.ENVIRONMENT}. "
            "Set it (infra/secrets/manifest.json → Secrets Manager → task def) "
            "so failures are reported. Refusing to start blind."
        )
