"""Turn a stored photo URL into one a client can actually load.

Photos are stored as their canonical S3 URL (`https://{bucket}.s3.{region}
.amazonaws.com/{key}`) — but the bucket is PRIVATE, so that raw URL 403s for
any client. It must be presigned on read. Signing is pure local computation
(no network), so this is a synchronous helper safe to call during response
serialization — the response schemas (outfit photo, profile photo) run
every stored URL through it so every endpoint returns a viewable
URL without each having to remember to presign.

Fail-safe by design: if storage isn't configured (tests/dev without S3) or
signing fails, the original value is returned unchanged — dev local
`/uploads/...` paths are served by the static mount and pass through as-is.

Related: services/blob_storage.py (facade), services/storage_s3.py (signer),
schemas/{session,user}.py (callers), constants/index.ts
`resolveUrl` on the mobile side (passes absolute URLs through untouched).
"""

import logging
from urllib.parse import urlparse

from app.services.blob_storage import BlobStorageService

logger = logging.getLogger(__name__)

# Cache the service (and its boto3 client) across calls. None once we've
# learned storage is unavailable, so we don't retry construction per photo.
_service: BlobStorageService | None = None
_service_ready = False
# Presigning runs per photo per response: report the first failure with its
# stack, then only warn, so a credentials problem is one event, not N per page.
_presign_failure_reported = False


def _get_service() -> BlobStorageService | None:
    global _service, _service_ready
    if not _service_ready:
        _service_ready = True
        try:
            _service = BlobStorageService()
        except Exception:
            logger.exception(
                "blob storage init failed — photo URLs will be served unsigned"
            )
            _service = None
    return _service


def to_viewable_url(stored_url: str | None) -> str | None:
    """Presign a stored S3 photo URL for client viewing. Returns None/empty and
    local `/uploads/...` paths unchanged; on any failure returns the original
    URL so a signing hiccup never blanks out a photo."""
    global _presign_failure_reported
    if not stored_url or stored_url.startswith("/"):
        return stored_url
    service = _get_service()
    if service is None:
        return stored_url
    try:
        key = urlparse(stored_url).path.lstrip("/")
        signed = service.generate_presigned_url_sync(key)
        # A success re-arms the latch: the NEXT outage reports again.
        _presign_failure_reported = False
        return signed or stored_url
    except Exception:  # benign: reported once per outage (below), then warned
        if _presign_failure_reported:
            logger.warning("photo presign failed", exc_info=True)
        else:
            _presign_failure_reported = True
            logger.exception("photo presign failed")
        return stored_url
