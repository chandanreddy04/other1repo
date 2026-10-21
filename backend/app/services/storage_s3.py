"""AWS S3 storage backend.

Implements `StorageBackend` (see `app.services.blob_storage`) for AWS deploys.
Selected by `STORAGE_BACKEND=s3`. Bucket/region come from `AWS_S3_BUCKET` and
`AWS_S3_REGION`; AWS credentials come from boto3's default chain (IAM task
role in ECS, env vars in dev).

This module is lazy-imported by `blob_storage._make_backend` so callers that
never touch storage don't pay the boto3 import cost. Tests live in
`tests/test_storage_s3.py`.

Related: infra/aws/ (S3 bucket + ECS task role with s3:* permissions),
         services/blob_storage.py (facade + factory).
"""

import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class S3Backend:
    """AWS S3 backend for photo storage. Selected by `STORAGE_BACKEND=s3`.

    NOTE: boto3's S3 client is sync; calls inside the async methods below
    block the event loop briefly. This is acceptable for short object
    operations. If we ever move to a truly async SDK (aioboto3), this
    wrapping should be revisited.
    """

    def __init__(self) -> None:
        if not settings.AWS_S3_BUCKET:
            raise ValueError("AWS_S3_BUCKET must be set when STORAGE_BACKEND=s3")
        # Fall back to the standard AWS env so local runs that just `export
        # AWS_DEFAULT_REGION=...` work without setting our app-specific name.
        region = settings.AWS_S3_REGION or os.environ.get("AWS_DEFAULT_REGION", "")
        if not region:
            raise ValueError(
                "AWS region must be set when STORAGE_BACKEND=s3 "
                "(via AWS_S3_REGION or AWS_DEFAULT_REGION)"
            )
        self.bucket = settings.AWS_S3_BUCKET
        self.region = region
        # boto3 picks up credentials from the default chain (IAM role / env).
        self.client = boto3.client("s3", region_name=self.region)

    async def upload_file(
        self, file_content: bytes, file_key: str, content_type: str
    ) -> str:
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=file_key,
                Body=file_content,
                ContentType=content_type,
            )
            # Canonical storage URL — NOT a readable URL. The bucket is private;
            # clients fetch via `generate_presigned_url` below. We return this
            # form so callers can store it as the file's permanent identifier.
            return f"https://{self.bucket}.s3.{self.region}.amazonaws.com/{file_key}"
        except (BotoCoreError, ClientError):
            # exception() carries exc_info, so the 5xx handler can dedupe the
            # HTTPException(500) raised `from` this by identity.
            logger.exception("Failed to upload file to S3")
            raise

    async def delete_file(self, file_key: str) -> bool:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=file_key)
            return True
        except (BotoCoreError, ClientError) as e:
            logger.error("Failed to delete file from S3: %s", e)
            return False

    def generate_presigned_url_sync(
        self, file_key: str, expiration: int = 3600
    ) -> str | None:
        # Pure client-side signing — no HTTP call to S3, so failures are
        # configuration errors (bad params, missing signer config), not
        # network errors. Sync because signing never blocks on I/O; callers
        # in a sync context (response serialization) use this directly.
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": file_key},
                ExpiresIn=expiration,
            )
        except (BotoCoreError, ClientError) as e:
            logger.error("Failed to generate S3 presigned URL: %s", e)
            return None

    async def generate_presigned_url(
        self, file_key: str, expiration: int = 3600
    ) -> str | None:
        return self.generate_presigned_url_sync(file_key, expiration)
