"""AWS SNS SMS backend.

Implements `SMSBackend` (see `app.services.sms`) as a Twilio failover for
AWS deploys. Selected by `SMS_FAILOVER_PROVIDER=sns`. Region is configured
via `AWS_SNS_REGION` (or `AWS_DEFAULT_REGION`); credentials come from
boto3's default chain (IAM task role in ECS, env vars in dev).

This module is lazy-imported by `sms._make_failover_backend` to keep
boto3 off the import path until first use. Tests live in
`tests/test_sms_sns.py`.

Delivery receipts: SNS sends delivery status to a CloudWatch Logs group,
not via webhook. The AWS Terraform (PR 12) provisions a Lambda
that forwards delivery events to the backend's SNS delivery webhook
(added in PR 5). The webhook key for that bridge lives in
`AWS_SNS_DELIVERY_WEBHOOK_SECRET`.

Related: services/sms.py (factory + facade),
         api/v1/endpoints/delivery_webhooks.py (PR 5 — sns_delivery_webhook),
         infra/aws/ (PR 12 — Lambda bridge).
"""

import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.models.alert import SMSProvider
from app.services.sms import SMSResult
from app.utils.phone import phone_tag

logger = logging.getLogger(__name__)


class _SNSBackend:
    """AWS SNS backend for failover SMS. Selected by `SMS_FAILOVER_PROVIDER=sns`.

    NOTE: boto3 SNS client is sync; calls inside async methods block the
    event loop briefly — tolerated since this only runs on Twilio failure.

    Degrades gracefully when unconfigured (no AWS region): the client stays
    None, `configured` is False, and sends report failure — matching the
    Twilio backend's posture so a dev/test boot without AWS env never
    crashes at import time (SMSService instantiates the failover eagerly).
    """

    provider_enum: SMSProvider = SMSProvider.SNS

    def __init__(self) -> None:
        # Resolution order: app-specific AWS_SNS_REGION wins over standard
        # AWS_DEFAULT_REGION so an operator can route SMS to a different
        # region than the rest of the app's AWS traffic if needed.
        self.client = None
        self.region = settings.AWS_SNS_REGION or os.environ.get(
            "AWS_DEFAULT_REGION", ""
        )
        self.sender_id = settings.AWS_SNS_SENDER_ID  # optional; empty = default
        if not self.region:
            logger.error(
                "SNS failover unconfigured: no AWS_SNS_REGION/AWS_DEFAULT_REGION "
                "— failover sends will report failure until a region is set"
            )
            return
        try:
            self.client = boto3.client("sns", region_name=self.region)
        except Exception:
            logger.exception("Failed to initialize SNS client")

    @property
    def configured(self) -> bool:
        # SNS requires no per-account setup beyond IAM (no phone number to
        # provision). True here means "client object exists"; IAM/credentials
        # failures surface lazily at first publish.
        return self.client is not None

    async def send_sms(self, to_phone: str, message: str) -> SMSResult:
        # Caller is responsible for E164 normalization (done upstream via the
        # `phonenumbers` lib). SNS rejects non-E164 with InvalidParameter and
        # we surface that as `result.success=False` like any other backend error.
        if not self.configured:
            logger.error("SNS not configured — cannot fail over from Twilio")
            return SMSResult(
                success=False,
                error="SNS not configured",
                provider=SMSProvider.SNS,
            )
        assert self.client is not None  # guarded by `configured` above
        try:
            # boto3 type accepts str | bytes (BinaryValue) but we only use
            # string attributes here.
            attrs: dict[str, dict[str, str | bytes]] = {
                # Transactional SMS — higher delivery priority + cost. OTP and
                # safety alerts both qualify; never use Promotional for this app.
                "AWS.SNS.SMS.SMSType": {
                    "DataType": "String",
                    "StringValue": "Transactional",
                },
            }
            if self.sender_id:
                attrs["AWS.SNS.SMS.SenderID"] = {
                    "DataType": "String",
                    "StringValue": self.sender_id,
                }
            resp = self.client.publish(
                PhoneNumber=to_phone,
                Message=message,
                MessageAttributes=attrs,
            )
            message_id = resp.get("MessageId")
            if not message_id:
                return SMSResult(
                    success=False,
                    error="SNS returned no MessageId",
                    provider=SMSProvider.SNS,
                )
            logger.info("SNS SMS sent: %s", message_id)
            return SMSResult(
                success=True, message_id=message_id, provider=SMSProvider.SNS
            )
        except (BotoCoreError, ClientError) as e:
            logger.exception("SNS error sending SMS to %s", phone_tag(to_phone))
            return SMSResult(success=False, error=str(e), provider=SMSProvider.SNS)
