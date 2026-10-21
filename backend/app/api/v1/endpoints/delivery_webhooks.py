"""SMS delivery status webhooks for Twilio and AWS SNS.

- Twilio: POST with form-encoded body + X-Twilio-Signature header.
- SNS: forwarded by the Lambda bridge (CloudWatch Logs subscription)
       with an HMAC-SHA256 signature header.

Both update alert status so the cron can retry FAILED deliveries.

Related: crud/alert.py, services/sms.py,
         infra/aws/ (SNS delivery → CloudWatch Logs → Lambda → this endpoint).
"""

import hashlib
import hmac
import json
import logging
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from twilio.request_validator import RequestValidator

from app.api.v1.deps.db import get_db
from app.core.config import settings
from app.crud import crud_notification_delivery
from app.services.notification_outbox import rollup_alert_status
from app.services.notification_policy import policy_for

logger = logging.getLogger(__name__)

router = APIRouter()


async def _apply_sms_receipt(
    db: AsyncSession, provider_message_id: str, *, delivered: bool | None
) -> None:
    """Resolve the notification_deliveries row for a provider message id and
    apply the receipt: delivered=True → delivered; False → failed (back off and
    retry); None → ignore. Rolls the linked Alert.status up."""
    if not provider_message_id or delivered is None:
        return
    delivery = await crud_notification_delivery.get_by_provider_message_id(
        db, provider_message_id
    )
    if not delivery:
        logger.debug("SMS receipt for unknown message id %s", provider_message_id)
        return
    now = datetime.now(UTC)
    if delivered:
        await crud_notification_delivery.mark_delivered(db, delivery=delivery, now=now)
    else:
        policy = policy_for(delivery.kind)
        await crud_notification_delivery.mark_failed_with_backoff(
            db,
            delivery=delivery,
            backoff_seconds=policy.backoff_seconds,
            max_attempts=policy.max_attempts,
            error="sms delivery failed (provider receipt)",
            now=now,
        )
    await rollup_alert_status(db, delivery.alert_id, now)
    await db.commit()


# ---------------------------------------------------------------------------
# Twilio delivery status callback
# ---------------------------------------------------------------------------


@router.post("/delivery/twilio")
async def twilio_delivery_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    signature = request.headers.get("X-Twilio-Signature", "")

    form = await request.form()
    params = dict(form)

    token_usable = bool(settings.TWILIO_AUTH_TOKEN) and (
        settings.TWILIO_AUTH_TOKEN != "your-auth-token"
    )
    if token_usable:
        validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
        url = str(request.url)
        if not validator.validate(url, params, signature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Twilio signature",
            )
    elif settings.ENVIRONMENT == "production":
        # Fail closed: this endpoint mutates alert delivered/failed state, so an
        # unauthenticated caller must not be allowed through on a misconfigured
        # token in production. Mirrors inbound_sms.py.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Twilio signature validation unavailable",
        )

    message_sid = params.get("MessageSid", "")
    message_status = params.get("MessageStatus", "")

    if not message_sid:
        return {"status": "ignored"}

    delivered = {"delivered": True, "failed": False, "undelivered": False}.get(
        message_status
    )
    await _apply_sms_receipt(db, message_sid, delivered=delivered)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# AWS SNS delivery status callback (via Lambda bridge)
# ---------------------------------------------------------------------------
#
# SNS doesn't post delivery receipts directly — it writes them to a CloudWatch
# Logs group. A Lambda (provisioned in PR 12) subscribes to that log group,
# parses the SNS delivery records, and POSTs them here. The Lambda computes
# `X-MIH-Signature: hex(HMAC-SHA256(secret, raw_body))` so we can verify the
# body wasn't tampered with in transit (the public endpoint can otherwise be
# called by anyone who guesses the URL).
#
# Expected payload (single record or list):
#   {"notification": {"messageId": "..."}, "status": "SUCCESS" | "FAILURE"}


def _verify_sns_signature(body: bytes, header: str) -> bool:
    """Constant-time HMAC verification. Returns False if the secret isn't
    configured (so the endpoint is closed by default in environments that
    haven't opted in)."""
    if not settings.AWS_SNS_DELIVERY_WEBHOOK_SECRET:
        return False
    expected = hmac.new(
        settings.AWS_SNS_DELIVERY_WEBHOOK_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return secrets.compare_digest(expected, header or "")


@router.post("/delivery/sns")
async def sns_delivery_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    raw = await request.body()
    provided = request.headers.get("X-MIH-Signature", "")
    if not _verify_sns_signature(raw, provided):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid SNS delivery signature",
        )

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body is not valid JSON",
        ) from e

    if not isinstance(body, list):
        body = [body]

    for event in body:
        if not isinstance(event, dict):
            continue
        message_id = event.get("notification", {}).get("messageId", "")
        delivery_status = event.get("status", "")
        if not message_id:
            continue
        delivered = {"SUCCESS": True, "FAILURE": False}.get(delivery_status)
        await _apply_sms_receipt(db, message_id, delivered=delivered)

    return {"status": "ok"}
