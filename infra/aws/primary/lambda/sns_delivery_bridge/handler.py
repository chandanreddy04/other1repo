"""SNS SMS delivery status → backend webhook bridge.

Subscribed to the CloudWatch Logs group SNS writes SMS delivery status
to (account-level configuration). On each batch of log events:

  1. Decode the CW Logs payload (gzip + base64).
  2. Parse each log message as the SNS delivery JSON.
  3. Project to the backend's webhook payload shape:
         {"notification": {"messageId": "..."}, "status": "SUCCESS"|"FAILURE"}
  4. HMAC-SHA256 sign the JSON body with the shared secret.
  5. POST to the backend's /webhooks/delivery/sns endpoint.

The backend's webhook (added in PR 5) ignores unknown messageIds, so
this Lambda can safely forward every delivery event even when staging
and production share the SNS log group (each backend only acts on the
records that match an Alert it dispatched).

Retry semantics: CloudWatch Logs invokes Lambda asynchronously and
retries on raised exceptions (up to 2 retries by default). We RAISE on
network errors and 5xx so transient failures retry, but RETURN normally
on 4xx so permanent failures don't burn the retry budget.
"""

import base64
import gzip
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_secrets = boto3.client("secretsmanager")
_cached_secret: str | None = None


def _required_env(name: str) -> str:
    """Read a required env var with a clear error message on miss —
    surfaces config bugs at invocation time, not opaquely at import."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required env var {name!r} is not set")
    return value


def _get_secret(secret_arn: str) -> str:
    """Fetch the HMAC shared secret once per cold start."""
    global _cached_secret
    if _cached_secret is None:
        resp = _secrets.get_secret_value(SecretId=secret_arn)
        _cached_secret = resp["SecretString"]
    return _cached_secret


def _parse_records(payload: dict) -> list[dict]:
    """Extract (messageId, status) pairs from the CW Logs payload.

    SNS emits PENDING/SUCCESS/FAILURE — only terminal states are
    forwarded; non-terminal records are logged at debug level so
    debugging "where did my delivery go?" stays possible.
    """
    records = []
    for log_event in payload.get("logEvents", []):
        try:
            data = json.loads(log_event["message"])
        except (json.JSONDecodeError, KeyError):
            # SNS sometimes emits non-JSON setup lines; skip silently.
            continue
        message_id = data.get("notification", {}).get("messageId", "")
        status = data.get("status", "")
        if message_id and status in ("SUCCESS", "FAILURE"):
            records.append(
                {"notification": {"messageId": message_id}, "status": status}
            )
        else:
            logger.debug(
                "Skipping non-terminal delivery record: status=%s message_id=%s",
                status,
                message_id,
            )
    return records


def handler(event: dict, context) -> dict:
    webhook_url = _required_env("BACKEND_WEBHOOK_URL")
    secret_arn = _required_env("WEBHOOK_SECRET_ARN")
    timeout = float(os.environ.get("REQUEST_TIMEOUT", "10"))

    raw = base64.b64decode(event["awslogs"]["data"])
    payload = json.loads(gzip.decompress(raw))
    records = _parse_records(payload)

    if not records:
        logger.info("No actionable delivery records in batch; skipping POST")
        return {"forwarded": 0}

    try:
        secret = _get_secret(secret_arn)
    except (BotoCoreError, ClientError) as e:
        logger.error("Failed to load webhook secret: %s", e)
        raise  # transient — let CW Logs retry

    body = json.dumps(records).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    req = urllib.request.Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-MIH-Signature": signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (url is trusted env)
            logger.info("Forwarded %d records, status=%d", len(records), resp.status)
            return {"forwarded": len(records), "status": resp.status}
    except urllib.error.HTTPError as e:
        # 4xx = permanent (bad signature, malformed) — don't retry.
        # 5xx = transient (backend down) — re-raise so CW Logs retries.
        if 400 <= e.code < 500:
            logger.error(
                "Backend returned %d (permanent); dropping %d records: %s",
                e.code,
                len(records),
                e.reason,
            )
            return {"forwarded": 0, "status": e.code, "dropped": len(records)}
        logger.warning(
            "Backend returned %d (transient); will retry %d records",
            e.code,
            len(records),
        )
        raise
    except urllib.error.URLError as e:
        # DNS / connection errors — always transient.
        logger.warning("Connection error forwarding to backend: %s", e)
        raise
