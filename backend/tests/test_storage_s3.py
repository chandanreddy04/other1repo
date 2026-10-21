"""Tests for the AWS S3 storage backend (`storage_s3.S3Backend`).

Uses moto to mock the S3 API end-to-end — every call goes through real boto3
to an in-memory S3 server. This catches API misuse (wrong arg names, bad
request shape) that pure mocks miss.

Moto's `@mock_aws` decorator wraps a sync function, which conflicts with
`pytest-asyncio`; we use the `mock_aws()` context manager inside each async
test instead.
"""

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

BUCKET = "test-photos"
REGION = "us-west-2"


def _set_s3_env(monkeypatch):
    monkeypatch.setattr("app.services.storage_s3.settings.AWS_S3_BUCKET", BUCKET)
    monkeypatch.setattr("app.services.storage_s3.settings.AWS_S3_REGION", REGION)
    # boto3 needs *some* creds to bypass the credential chain in CI.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


def _make_bucket() -> None:
    boto3.client("s3", region_name=REGION).create_bucket(
        Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION}
    )


@pytest.mark.asyncio
class TestS3Backend:
    async def test_init_requires_bucket(self, monkeypatch):
        monkeypatch.setattr("app.services.storage_s3.settings.AWS_S3_BUCKET", "")
        from app.services.storage_s3 import S3Backend

        with pytest.raises(ValueError, match="AWS_S3_BUCKET"):
            S3Backend()

    async def test_upload_file_success(self, monkeypatch):
        _set_s3_env(monkeypatch)
        with mock_aws():
            _make_bucket()
            from app.services.storage_s3 import S3Backend

            backend = S3Backend()
            url = await backend.upload_file(b"image-bytes", "photos/x.jpg", "image/jpeg")

            assert url == f"https://{BUCKET}.s3.{REGION}.amazonaws.com/photos/x.jpg"
            obj = boto3.client("s3", region_name=REGION).get_object(
                Bucket=BUCKET, Key="photos/x.jpg"
            )
            assert obj["Body"].read() == b"image-bytes"
            assert obj["ContentType"] == "image/jpeg"

    async def test_upload_file_failure_raises(self, monkeypatch):
        _set_s3_env(monkeypatch)
        with mock_aws():
            # Bucket intentionally NOT created — put_object raises NoSuchBucket.
            from app.services.storage_s3 import S3Backend

            backend = S3Backend()
            with pytest.raises(ClientError) as exc:
                await backend.upload_file(b"x", "k", "image/jpeg")
            assert exc.value.response["Error"]["Code"] == "NoSuchBucket"

    async def test_delete_file_success(self, monkeypatch):
        _set_s3_env(monkeypatch)
        with mock_aws():
            _make_bucket()
            s3 = boto3.client("s3", region_name=REGION)
            s3.put_object(Bucket=BUCKET, Key="photos/y.jpg", Body=b"x")
            from app.services.storage_s3 import S3Backend

            backend = S3Backend()
            ok = await backend.delete_file("photos/y.jpg")

            assert ok is True
            # Subsequent head_object should 404.
            with pytest.raises(ClientError):
                s3.head_object(Bucket=BUCKET, Key="photos/y.jpg")

    async def test_delete_missing_key_is_idempotent(self, monkeypatch):
        """S3 DeleteObject on a nonexistent KEY returns success (204) — that's
        the real contract, and the cleanup loop relies on it (deleting an
        already-deleted photo should not fail the run)."""
        _set_s3_env(monkeypatch)
        with mock_aws():
            _make_bucket()
            from app.services.storage_s3 import S3Backend

            backend = S3Backend()
            ok = await backend.delete_file("photos/nonexistent.jpg")

            assert ok is True

    async def test_generate_presigned_url_success(self, monkeypatch):
        _set_s3_env(monkeypatch)
        with mock_aws():
            _make_bucket()
            from app.services.storage_s3 import S3Backend

            backend = S3Backend()
            url = await backend.generate_presigned_url("photos/z.jpg", expiration=120)

            assert url is not None
            assert BUCKET in url
            assert "photos/z.jpg" in url
            # moto emits SigV2 (`Signature=`); real S3 / newer boto configs
            # use SigV4 (`X-Amz-Signature=`). Accept either.
            assert "Signature=" in url or "X-Amz-Signature=" in url


@pytest.mark.asyncio
class TestS3BackendViaFactory:
    """End-to-end: setting STORAGE_BACKEND=s3 returns an S3Backend through
    the BlobStorageService facade."""

    async def test_factory_returns_s3_backend(self, monkeypatch):
        _set_s3_env(monkeypatch)
        with mock_aws():
            _make_bucket()
            from app.services import blob_storage
            from app.services.storage_s3 import S3Backend

            monkeypatch.setattr(blob_storage.settings, "STORAGE_BACKEND", "s3")
            backend = blob_storage._make_backend()

            assert isinstance(backend, S3Backend)
