"""Inbound SMS webhook (Twilio Messaging Service → us).

Branches on the body:
  - Protected STOP keyword: Twilio already sent the static 1b confirmation
    and marked the number opted-out on its side. We mirror the state on
    our side, cascade the contact's circle memberships to OPTED_OUT, and
    fan out the per-owner push.
  - Protected START keyword: opposite — clear opt-out, restore memberships.
  - Soft-stop-adjacent phrase ("please stop", "remove me", etc.): we
    haven't opted them out yet. Send the personalized 1c gate (if we
    haven't already in the last 24h) so they realize what STOP actually
    costs them.
  - Anything else: log and acknowledge, no action.

Twilio's Advanced Opt-Out owns the literal STOP/START/HELP customer-facing
reply. This webhook is purely about reflecting and cascading the state
inside our system.

Related: services/sms_opt_out.py, services/notification_helpers.py,
         api/v1/endpoints/delivery_webhooks.py (sibling Twilio webhook).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.services import sms_opt_out
from app.services.notification_helpers import (
    fan_out_cascade_notifications,
    render_soft_stop_gate,
    send_account_holder_unsubscribed,
)
from app.services.sms import sms_service
from app.utils.phone import phone_tag

logger = logging.getLogger(__name__)

router = APIRouter()

_EMPTY_TWIML = str(MessagingResponse())


@router.post("/sms/twilio-inbound")
async def twilio_inbound_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    form = await request.form()
    params = dict(form)

    # Twilio signature validation. In dev/test the auth token may be
    # empty or the placeholder, in which case we skip — but in production
    # an unset token is a misconfiguration, not "skip validation". Fail
    # closed there so a forgotten secret can't turn the webhook into an
    # open cascade trigger.
    token_unusable = (
        not settings.TWILIO_AUTH_TOKEN
        or settings.TWILIO_AUTH_TOKEN == "your-auth-token"
    )
    if token_unusable and settings.ENVIRONMENT == "production":
        # No log here: the 5xx handler in main.py logs and reports it (ERROR).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook misconfigured",
        )
    if not token_unusable:
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        signature = request.headers.get("X-Twilio-Signature", "")
        if not validator.validate(str(request.url), params, signature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Twilio signature",
            )

    from_phone = str(params.get("From", "")).strip()
    raw_body = str(params.get("Body", "")).strip()

    if not from_phone:
        logger.warning("inbound_sms_missing_from", extra={"params": list(params)})
        return Response(content=_EMPTY_TWIML, media_type="application/xml")

    upper_body = raw_body.upper()

    if upper_body in sms_opt_out.PROTECTED_STOP_KEYWORDS:
        await _handle_stop(db, from_phone)
        return Response(content=_EMPTY_TWIML, media_type="application/xml")

    if upper_body in sms_opt_out.PROTECTED_START_KEYWORDS:
        await sms_opt_out.record_opt_in(db, from_phone)
        logger.info("inbound_sms_start", extra={"phone_tag": phone_tag(from_phone)})
        return Response(content=_EMPTY_TWIML, media_type="application/xml")

    if sms_opt_out.soft_stop_intent(raw_body):
        await _handle_soft_stop(db, from_phone)
        return Response(content=_EMPTY_TWIML, media_type="application/xml")

    logger.info(
        "inbound_sms_unhandled",
        extra={
            "phone_tag": phone_tag(from_phone),
            "body_len": len(raw_body),
        },
    )
    return Response(content=_EMPTY_TWIML, media_type="application/xml")


async def _handle_stop(db: AsyncSession, from_phone: str) -> None:
    phone = await sms_opt_out.record_opt_out(db, from_phone)
    if phone is None:
        # No record of this phone — Twilio still honors the STOP on its
        # side; we just have no memberships to cascade. Log and move on.
        logger.info(
            "inbound_sms_stop_unknown_phone", extra={"phone_tag": phone_tag(from_phone)}
        )
        return
    impacts = await sms_opt_out.cascade_circle_removal(db, phone)
    if impacts:
        await fan_out_cascade_notifications(db, impacts)
    logger.info(
        "inbound_sms_stop_cascade",
        extra={
            "phone_tag": phone_tag(from_phone),
            "affected_owners": len(impacts),
        },
    )

    # Account-holder STOP: their own phone (not just a contact's). They
    # just locked themselves out of OTP and our SMS, which is
    # essentially "unsubscribing from the app." Tell them explicitly
    # via push — they may not realize the consequence.
    account_user = await sms_opt_out.user_for_phone(db, phone.id)
    if account_user is not None:
        try:
            # Enqueues + dispatches inline via the outbox (owner decision:
            # every push auditable) and commits as part of that
            # (enqueue_and_send). A provider failure during the inline
            # dispatch is swallowed there — the reconciler retries; this
            # only guards a DB-layer failure while enqueuing the row.
            # The opt-out (record_opt_out) and the cascade
            # (cascade_circle_removal, fan_out_cascade_notifications) have
            # each committed already, so a failure here can't undo them.
            await send_account_holder_unsubscribed(db, account_user)
        except Exception:
            logger.exception(
                "account_holder_unsubscribe_push_failed",
                extra={"user_id": str(account_user.id)},
            )
            # A DB error in the outbox insert aborts the open transaction;
            # roll it back so get_db's commit-on-exit doesn't raise and the
            # webhook still acks Twilio with a 200 (a non-2xx makes Twilio
            # retry the STOP). Only the un-committed push row is discarded.
            await db.rollback()


async def _handle_soft_stop(db: AsyncSession, from_phone: str) -> None:
    # 24h cooldown — without it, a contact who keeps texting "please
    # stop, please stop, please stop" gets one gate SMS per reply.
    if not await sms_opt_out.should_send_soft_stop_gate(db, from_phone):
        logger.info(
            "inbound_sms_soft_stop_cooldown_skipped",
            extra={"phone_tag": phone_tag(from_phone)},
        )
        return

    profile = await sms_opt_out.get_sender_profile(db, from_phone)
    body = render_soft_stop_gate(profile)
    # Wrap the dispatch + stamp so an SMS-provider error doesn't 500 the
    # webhook — Twilio would retry indefinitely on a non-2xx and we'd
    # never set the cooldown timestamp. Log and ack instead.
    try:
        # Send via our SMS service (not TwiML) so it goes through the
        # same outbound pipeline — gives us delivery callbacks and is
        # consistent with how the rest of our SMS goes out.
        await sms_service.send_sms(to_phone=from_phone, message=body)
        await sms_opt_out.record_soft_stop_gate_sent(db, from_phone)
    except Exception:
        logger.exception(
            "inbound_sms_soft_stop_dispatch_failed",
            extra={"phone_tag": phone_tag(from_phone)},
        )
