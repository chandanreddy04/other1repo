"""Cloud object storage service (AWS S3).

The `STORAGE_BACKEND` env var selects the backend; `s3` (AWS S3) is the
only supported value. The facade keeps the selection seam so a second
backend can be reintroduced without touching callers.

Public surface (`BlobStorageService`) is a facade so callers don't couple
to the concrete backend. This wrapper is also the seam for cross-cutting
concerns (metrics, retries, request-id propagation) that should apply to
any backend uniformly; add them here, not in the backend classes.

Related: services/storage_s3.py (backend), services/file_upload.py
(caller), services/session_tasks.py (cleanup), infra/aws/ (S3 bucket).
"""

import logging
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from app.core.config import settings

logger = logging.getLogger(__name__)


@runtime_checkable
class StorageBackend(Protocol):
    """Backend interface for cloud object storage."""

    async def upload_file(
        self, file_content: bytes, file_key: str, content_type: str
    ) -> str:
        """Upload bytes under `file_key` and return the public URL.

        Raises the backend's native error on failure (the caller surfaces a
        500 to the user).
        """
        ...

    async def delete_file(self, file_key: str) -> bool:
        """Delete `file_key`. Return True on success, False on backend error
        (callers treat missing/deleted as success-ish; cleanup loops tolerate
        missing files)."""
        ...

    async def generate_presigned_url(
        self, file_key: str, expiration: int = 3600
    ) -> str | None:
        """Return a time-limited signed URL for `file_key`, or None if the
        backend cannot produce one (e.g. missing credentials)."""
        ...

    def generate_presigned_url_sync(
        self, file_key: str, expiration: int = 3600
    ) -> str | None:
        """Synchronous presign — signing is pure local computation (no network
        I/O), so it's safe to call during response serialization. Same return
        contract as the async form."""
        ...


def _make_s3_backend() -> StorageBackend:
    # Lazy import keeps boto3 off the import path until first use.
    from app.services.storage_s3 import S3Backend
    return S3Backend()


# Single source of truth for supported backends.
_BACKENDS: dict[str, Callable[[], StorageBackend]] = {
    "s3": _make_s3_backend,
}


def _make_backend() -> StorageBackend:
    """Pick the storage backend based on `settings.STORAGE_BACKEND`.

    Env-var value is lowercased so `S3` doesn't silently fall through to
    the default-rejection path.
    """
    name = settings.STORAGE_BACKEND.lower()
    factory = _BACKENDS.get(name)
    if factory is None:
        raise ValueError(
            f"Unknown STORAGE_BACKEND: {name!r} "
            f"(supported: {sorted(_BACKENDS)})"
        )
    return factory()


class BlobStorageService:
    """Storage facade. Delegates to the backend selected by `STORAGE_BACKEND`."""

    def __init__(self) -> None:
        self._backend: StorageBackend = _make_backend()

    async def upload_file(
        self, file_content: bytes, file_key: str, content_type: str
    ) -> str:
        return await self._backend.upload_file(file_content, file_key, content_type)

    async def delete_file(self, file_key: str) -> bool:
        return await self._backend.delete_file(file_key)

    async def generate_presigned_url(
        self, file_key: str, expiration: int = 3600
    ) -> str | None:
        return await self._backend.generate_presigned_url(file_key, expiration)

    def generate_presigned_url_sync(
        self, file_key: str, expiration: int = 3600
    ) -> str | None:
        return self._backend.generate_presigned_url_sync(file_key, expiration)


_instance: BlobStorageService | None = None


def get_blob_storage_service() -> BlobStorageService:
    global _instance
    if _instance is None:
        _instance = BlobStorageService()
    return _instance
