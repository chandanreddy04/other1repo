import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings
from app.utils.image_validation import validate_image

logger = logging.getLogger(__name__)

LOCAL_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
_EXT_BY_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


async def _save_locally(file_content: bytes, file_key: str) -> str:
    """Save file to local disk and return a URL served by the static mount."""
    dest = LOCAL_UPLOAD_DIR / file_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(file_content)
    logger.info("Saved upload locally: %s", dest)
    return f"/uploads/{file_key}"


async def upload_image(
    file: UploadFile, prefix: str, user_id: UUID, max_size_mb: int = 5
) -> str:
    """Validate image, generate filename, upload to S3 (or local in dev), return URL."""
    try:
        file_content = await validate_image(file, max_size_mb=max_size_mb)

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        extension = _EXT_BY_MIME.get(file.content_type or "", "jpg")
        filename = f"{prefix}/{user_id}/{timestamp}.{extension}"

        if settings.ENVIRONMENT == "development":
            return await _save_locally(file_content, filename)

        from app.services.blob_storage import get_blob_storage_service

        return await get_blob_storage_service().upload_file(
            file_content=file_content, file_key=filename, content_type=file.content_type or "image/jpeg"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload photo",
        ) from e
