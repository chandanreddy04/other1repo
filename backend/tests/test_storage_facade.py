"""Tests for the storage facade and backend factory.

The facade (`BlobStorageService`) and factory (`_make_backend`) let callers
stay unchanged while the backend is selected by `STORAGE_BACKEND`. S3 (AWS
S3) is the only supported backend. These tests verify the facade delegates
correctly and
the factory honors the env var.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import blob_storage
from app.services.blob_storage import (
    BlobStorageService,
    StorageBackend,
    _make_backend,
)


@pytest.mark.asyncio
class TestStorageFacade:
    """`BlobStorageService` should delegate every call to its backend unchanged."""

    def _make_facade_with_mock_backend(self) -> tuple[BlobStorageService, MagicMock]:
        facade = BlobStorageService.__new__(BlobStorageService)
        mock_backend = MagicMock()
        mock_backend.upload_file = AsyncMock(return_value="https://example/x")
        mock_backend.delete_file = AsyncMock(return_value=True)
        mock_backend.generate_presigned_url = AsyncMock(return_value="https://example/x?sig")
        facade._backend = mock_backend
        return facade, mock_backend

    async def test_upload_file_delegates_to_backend(self):
        facade, backend = self._make_facade_with_mock_backend()

        result = await facade.upload_file(b"content", "key", "image/jpeg")

        assert result == "https://example/x"
        backend.upload_file.assert_awaited_once_with(b"content", "key", "image/jpeg")

    async def test_delete_file_delegates_to_backend(self):
        facade, backend = self._make_facade_with_mock_backend()

        result = await facade.delete_file("key")

        assert result is True
        backend.delete_file.assert_awaited_once_with("key")

    async def test_generate_presigned_url_delegates_to_backend(self):
        facade, backend = self._make_facade_with_mock_backend()

        result = await facade.generate_presigned_url("key", expiration=120)

        assert result == "https://example/x?sig"
        backend.generate_presigned_url.assert_awaited_once_with("key", 120)


class TestStorageBackendFactory:
    def test_default_backend_is_s3(self, monkeypatch):
        from app.services.storage_s3 import S3Backend

        monkeypatch.setattr(blob_storage.settings, "STORAGE_BACKEND", "s3")
        monkeypatch.setattr(blob_storage.settings, "AWS_S3_BUCKET", "test-bucket")
        monkeypatch.setattr(blob_storage.settings, "AWS_S3_REGION", "us-west-2")

        backend = _make_backend()

        assert isinstance(backend, S3Backend)

    def test_env_var_is_case_insensitive(self, monkeypatch):
        from app.services.storage_s3 import S3Backend

        monkeypatch.setattr(blob_storage.settings, "STORAGE_BACKEND", "S3")
        monkeypatch.setattr(blob_storage.settings, "AWS_S3_BUCKET", "test-bucket")
        monkeypatch.setattr(blob_storage.settings, "AWS_S3_REGION", "us-west-2")

        backend = _make_backend()

        assert isinstance(backend, S3Backend)

    def test_unknown_backend_raises_value_error(self, monkeypatch):
        monkeypatch.setattr(blob_storage.settings, "STORAGE_BACKEND", "wat")

        with pytest.raises(ValueError, match="Unknown STORAGE_BACKEND"):
            _make_backend()

    def test_blob_storage_service_satisfies_storage_backend_protocol(self):
        # Runtime-checkable Protocol checks method *names* only, not signatures
        # or return types — so this catches "forgot to add a method" but not
        # "signature drifted." Signature drift is caught at the call site by
        # mypy + the delegation tests above.
        assert issubclass(BlobStorageService, StorageBackend)
